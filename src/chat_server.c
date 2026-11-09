#define _POSIX_C_SOURCE 200809L

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdatomic.h>
#include <inttypes.h>
#include <unistd.h>
#include <errno.h>
#include <time.h>
#include <stdarg.h>
#include <pthread.h>
#include <signal.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

#define NAME_MAX_LEN 32
#define RECV_BUFFER_SIZE (64 * 1024)   /* 64 KiB por recv */
#define MAX_CLIENTS 64
#define MAX_SAMPLES 3600

typedef struct {
    int fd;
    int index;
    char name[NAME_MAX_LEN];
    _Atomic uint64_t bytes_received;
    pthread_t tid;
} Client;

/* Estado global da rodada. Preenchido por main(), lido por threads. */
static Client *g_clients[MAX_CLIENTS];
static int g_num_registered = 0;
static int g_n_expected = 0;
static int g_duration_s = 0;
static int g_block_bytes = RECV_BUFFER_SIZE;
static int g_rep_id = 0;
static int g_warmup_s = 5;
static int g_cooldown_s = 5;
static int g_quiet = 0;
static const char *g_results_path = "results.csv";
static const char *g_samples_path = "samples.csv";
static const char *g_label = "";

static pthread_mutex_t g_register_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_barrier_t g_start_barrier;
static struct timespec g_t_start;

/* Snapshot por segundo: samples[tick][i] = bytes do cliente i no tick. */
static uint64_t g_samples[MAX_SAMPLES][MAX_CLIENTS];
static int g_samples_count = 0;
static volatile sig_atomic_t g_measurement_active = 0;

static void logmsg(const char *fmt, ...) {
    if (g_quiet) return;
    va_list ap;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
}

/* I/O utilitarios                                                     */

/* Envia todos os bytes, lidando com envios parciais e EINTR. */
static int send_all(int fd, const char *data, size_t len) {
    size_t sent = 0;
    while (sent < len) {
        ssize_t n = send(fd, data + sent, len - sent, MSG_NOSIGNAL);
        if (n == -1) {
            if (errno == EINTR) continue;
            return -1;
        }
        if (n == 0) return -1;
        sent += (size_t)n;
    }
    return 0;
}

static ssize_t read_line(int fd, char *buffer, size_t capacity) {
    size_t pos = 0;
    while (pos < capacity - 1) {
        char c;
        ssize_t n = recv(fd, &c, 1, 0);
        if (n == 0) return pos == 0 ? 0 : (ssize_t)pos;
        if (n == -1) {
            if (errno == EINTR) continue;
            return -1;
        }
        if (c == '\n') break;
        if (c != '\r') buffer[pos++] = c;
    }
    buffer[pos] = '\0';
    return (ssize_t)pos;
}

static double tdiff(const struct timespec *a, const struct timespec *b) {
    return (double)(b->tv_sec - a->tv_sec)
         + (double)(b->tv_nsec - a->tv_nsec) / 1e9;
}

/* Thread de cliente: caminho critico de recepcao                      */

static void *handle_client(void *arg) {
    Client *c = (Client *)arg;
    char name_buf[NAME_MAX_LEN];

    /*
     * Cada thread tem seu proprio buffer, sem compartilhamento.
     */
    char *buf = malloc(RECV_BUFFER_SIZE);
    if (!buf) {
        fprintf(stderr, "[server] malloc recv_buf: %s\n", strerror(errno));
        close(c->fd);
        return NULL;
    }

    /* le o nome do cliente. */
    ssize_t n = read_line(c->fd, name_buf, sizeof(name_buf));
    if (n <= 0 || name_buf[0] == '\0') {
        logmsg("[server] cliente fechou antes de enviar o nome\n");
        free(buf);
        close(c->fd);
        return NULL;
    }
    snprintf(c->name, sizeof(c->name), "%s", name_buf);

    /* Registra na tabela global. */
    pthread_mutex_lock(&g_register_mutex);
    c->index = g_num_registered;
    g_clients[g_num_registered] = c;
    g_num_registered++;
    pthread_mutex_unlock(&g_register_mutex);

    logmsg("[server] cliente %d/%d registrado: %s\n",
           c->index + 1, g_n_expected, c->name);

    /* barreira de sincronizacao com main e as outras threads. */
    pthread_barrier_wait(&g_start_barrier);

    /*
     * laco de recepcao. Caminho critico.
     *
     * - Buffer grande (64 KiB): uma syscall recv() por bloco, nao por byte.
     * - Nenhum mutex: contador atomico, nada mais.
     * - Nenhum printf, nenhum memcpy, nenhum broadcast.
     * - Dados sao descartados; so interessa o total de bytes.
     */
    while (1) {
        ssize_t r = recv(c->fd, buf, RECV_BUFFER_SIZE, 0);
        if (r == 0) break;             /* cliente fez shutdown(SHUT_WR) */
        if (r == -1) {
            if (errno == EINTR) continue;
            fprintf(stderr, "[server] recv erro em %s: %s\n",
                    c->name, strerror(errno));
            break;
        }
        atomic_fetch_add_explicit(&c->bytes_received,
                                  (uint64_t)r,
                                  memory_order_relaxed);
    }

    free(buf);
    return NULL;
}

/* Thread amostradora                                                  */

/*
 * Acorda a cada 1 segundo (em tempo absoluto relativo a t_start) e
 * grava um snapshot dos contadores de todas as threads.
 *
 * Nao toca nos sockets, nao segura mutex: so le atomicos.
 */
static void *sampler(void *arg) {
    (void)arg;
    struct timespec target = g_t_start;

    while (g_samples_count < MAX_SAMPLES) {
        target.tv_sec += 1;
        int rc = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME,
                                 &target, NULL);
        if (rc != 0 && rc != EINTR) break;

        /* Checa a flag DEPOIS do sleep: se a medicao terminou enquanto
         * dormiamos, nao gravamos uma amostra pos-morte. */
        if (!g_measurement_active) break;

        int tick = g_samples_count;
        for (int i = 0; i < g_num_registered; i++) {
            g_samples[tick][i] = atomic_load_explicit(
                &g_clients[i]->bytes_received,
                memory_order_relaxed);
        }
        g_samples_count++;
    }
    return NULL;
}

/* CSV: resumo e amostras                                              */

static void ensure_header(const char *path, const char *header) {
    FILE *f = fopen(path, "r");
    if (f) { fclose(f); return; }
    f = fopen(path, "w");
    if (!f) {
        fprintf(stderr, "[server] fopen %s: %s\n", path, strerror(errno));
        return;
    }
    fprintf(f, "%s\n", header);
    fclose(f);
}

static void write_summary(double total_s, double window_s,
                          uint64_t bytes_total, uint64_t bytes_window,
                          double mbps_total, double mbps_window) {
    ensure_header(g_results_path,
        "timestamp,label,rep,n_clients,block_bytes,duration_s,"
        "bytes_total,bytes_window,window_s,mbps_total,mbps_window");

    FILE *f = fopen(g_results_path, "a");
    if (!f) {
        fprintf(stderr, "[server] fopen %s: %s\n",
                g_results_path, strerror(errno));
        return;
    }

    time_t now = time(NULL);
    struct tm tm;
    localtime_r(&now, &tm);
    char ts[32];
    strftime(ts, sizeof(ts), "%Y-%m-%dT%H:%M:%S", &tm);

    fprintf(f,
        "%s,%s,%d,%d,%d,%.3f,%" PRIu64 ",%" PRIu64 ",%.3f,%.3f,%.3f\n",
        ts, g_label, g_rep_id, g_n_expected, g_block_bytes,
        total_s, bytes_total, bytes_window, window_s,
        mbps_total, mbps_window);

    fclose(f);
}

static void write_samples(void) {
    /* Cabecalho: timestamp,label,rep,n_clients,tick_s,bytes_total,
     *            bytes_c0,bytes_c1,...
     * Numero de colunas de cliente varia por rodada, entao cada rodada
     * grava um bloco com seu proprio cabecalho se for a primeira linha.
     * Para simplificar o pos-processamento, gravo no formato "longo":
     * uma linha por (tick, cliente).
     */
    ensure_header(g_samples_path,
        "timestamp,label,rep,n_clients,tick_s,client_index,client_name,"
        "bytes_cumulative");

    FILE *f = fopen(g_samples_path, "a");
    if (!f) {
        fprintf(stderr, "[server] fopen %s: %s\n",
                g_samples_path, strerror(errno));
        return;
    }

    time_t now = time(NULL);
    struct tm tm;
    localtime_r(&now, &tm);
    char ts[32];
    strftime(ts, sizeof(ts), "%Y-%m-%dT%H:%M:%S", &tm);

    for (int t = 0; t < g_samples_count; t++) {
        for (int i = 0; i < g_num_registered; i++) {
            fprintf(f,
                "%s,%s,%d,%d,%d,%d,%s,%" PRIu64 "\n",
                ts, g_label, g_rep_id, g_n_expected,
                t + 1, i, g_clients[i]->name,
                g_samples[t][i]);
        }
    }

    fclose(f);
}

/* CALCULO DOS RESULTADOS                                              */

/*
 * Vazao agregada:
 *
 *   R_agregada = 8 * soma_i(bytes_i) / (t1 - t0) * 1e-6  [Mbps]
 *
 * "bytes_i" = bytes efetivamente recebidos pela thread do cliente i.
 * (t1 - t0) = tempo medido no servidor, do envio do GO ao ultimo
 *             recv == 0.
 * O fator 8 converte bytes para bits; 1e-6 traz para Mbps decimal.
 */
static void compute_and_report(const struct timespec *t_end) {
    double total_s = tdiff(&g_t_start, t_end);

    uint64_t bytes_total = 0;
    for (int i = 0; i < g_num_registered; i++) {
        bytes_total += atomic_load(&g_clients[i]->bytes_received);
    }

    double mbps_total = (total_s > 0)
        ? (8.0 * (double)bytes_total) / (total_s * 1e6)
        : 0.0;

    /*
     * Janela estavel: descarta g_warmup_s no inicio e g_cooldown_s
     * no fim. Usa as amostras cumulativas:
     *   bytes_na_janela = sum_i [ samples_at(end_s) - samples_at(start_s) ]
     *
     * Convencoes:
     *   samples[k][i] = bytes do cliente i registrados na amostra k+1,
     *                   ou seja, imediatamente apos o segundo (k+1) da medicao.
     *   samples_at(0) = 0 (nada enviado ainda em t=0).
     *   samples_at(t) = samples[t-1] para t >= 1, saturando no ultimo tick.
     *
     * A janela so eh considerada valida se total_s > warmup + cooldown + 1.
     * Caso contrario, nao houve medicao estavel suficiente e reportamos
     * window_s = 0.
     */
    uint64_t bytes_window = 0;
    double window_s = 0.0;

    int min_duration = g_warmup_s + g_cooldown_s + 1;
    if (total_s >= (double)min_duration && g_samples_count > 0) {
        int start_s = g_warmup_s;
        int end_s = g_samples_count - g_cooldown_s;

        if (end_s > start_s) {
            for (int i = 0; i < g_num_registered; i++) {
                uint64_t a = (start_s > 0)
                    ? g_samples[start_s - 1][i]
                    : 0;
                uint64_t b = g_samples[end_s - 1][i];
                bytes_window += (b - a);
            }
            window_s = (double)(end_s - start_s);
        }
    }

    double mbps_window = (window_s > 0)
        ? (8.0 * (double)bytes_window) / (window_s * 1e6)
        : 0.0;

    logmsg("\n[server] ======================================\n");
    logmsg("[server] Rodada concluida.\n");
    logmsg("[server]   N clientes       : %d\n", g_num_registered);
    logmsg("[server]   Tempo total      : %.3f s\n", total_s);
    logmsg("[server]   Bytes totais     : %" PRIu64 "\n", bytes_total);
    logmsg("[server]   Vazao agregada   : %.2f Mbps (total)\n", mbps_total);
    logmsg("[server]   Janela estavel   : %.3f s (warmup=%ds, cooldown=%ds)\n",
           window_s, g_warmup_s, g_cooldown_s);
    logmsg("[server]   Bytes na janela  : %" PRIu64 "\n", bytes_window);
    logmsg("[server]   Vazao na janela  : %.2f Mbps\n", mbps_window);
    logmsg("[server] Por cliente:\n");
    for (int i = 0; i < g_num_registered; i++) {
        uint64_t b = atomic_load(&g_clients[i]->bytes_received);
        double mbps_i = (8.0 * (double)b) / (total_s * 1e6);
        logmsg("[server]   [%d] %-16s %12" PRIu64 " bytes  %.2f Mbps\n",
               i, g_clients[i]->name, b, mbps_i);
    }
    logmsg("[server] ======================================\n");

    write_summary(total_s, window_s, bytes_total, bytes_window,
                  mbps_total, mbps_window);
    write_samples();
}


static void usage(const char *prog) {
    fprintf(stderr,
        "Uso: %s -p <porta> -n <N> -d <duracao_s> [opcoes]\n"
        "Opcoes:\n"
        "  -o <arquivo>   CSV de resumo (append). Padrao: results.csv\n"
        "  -s <arquivo>   CSV de amostras (append). Padrao: samples.csv\n"
        "  -r <rep_id>    Identificador da repeticao. Padrao: 0\n"
        "  -b <bytes>     Tamanho do bloco (so registro). Padrao: 65536\n"
        "  -w <s>         Segundos de warmup. Padrao: 5\n"
        "  -c <s>         Segundos de cooldown. Padrao: 5\n"
        "  -l <label>     Rotulo da campanha. Padrao: \"\"\n"
        "  -q             Modo silencioso.\n",
        prog);
}

int main(int argc, char *argv[]) {
    int port = -1;

    int opt;
    while ((opt = getopt(argc, argv, "p:n:d:o:s:r:b:w:c:l:qh")) != -1) {
        switch (opt) {
            case 'p': port = atoi(optarg); break;
            case 'n': g_n_expected = atoi(optarg); break;
            case 'd': g_duration_s = atoi(optarg); break;
            case 'o': g_results_path = optarg; break;
            case 's': g_samples_path = optarg; break;
            case 'r': g_rep_id = atoi(optarg); break;
            case 'b': g_block_bytes = atoi(optarg); break;
            case 'w': g_warmup_s = atoi(optarg); break;
            case 'c': g_cooldown_s = atoi(optarg); break;
            case 'l': g_label = optarg; break;
            case 'q': g_quiet = 1; break;
            case 'h':
            default: usage(argv[0]); return EXIT_FAILURE;
        }
    }

    if (port <= 0 || g_n_expected <= 0 || g_duration_s <= 0 ||
        g_n_expected > MAX_CLIENTS) {
        usage(argv[0]);
        return EXIT_FAILURE;
    }

    signal(SIGPIPE, SIG_IGN);

    int server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd == -1) {
        perror("socket");
        return EXIT_FAILURE;
    }

    int one = 1;
    setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR,
               &one, sizeof(one));

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port = htons(port);

    if (bind(server_fd, (struct sockaddr *)&addr, sizeof(addr)) == -1) {
        perror("bind");
        close(server_fd);
        return EXIT_FAILURE;
    }

    if (listen(server_fd, g_n_expected + 4) == -1) {
        perror("listen");
        close(server_fd);
        return EXIT_FAILURE;
    }

    logmsg("[server] escutando na porta %d, esperando %d clientes...\n",
           port, g_n_expected);

    /*
     * Barreira com N clientes + a thread main. Todos passam quando os
     * N clientes tiverem conectado e lido o nome.
     */
    if (pthread_barrier_init(&g_start_barrier, NULL,
                             g_n_expected + 1) != 0) {
        fprintf(stderr, "[server] pthread_barrier_init falhou\n");
        close(server_fd);
        return EXIT_FAILURE;
    }

    /* Aceita exatamente N conexoes. */
    for (int accepted = 0; accepted < g_n_expected; accepted++) {
        int cfd = accept(server_fd, NULL, NULL);
        if (cfd == -1) {
            if (errno == EINTR) { accepted--; continue; }
            perror("accept");
            close(server_fd);
            return EXIT_FAILURE;
        }

        Client *c = calloc(1, sizeof(Client));
        if (!c) {
            perror("calloc");
            close(cfd);
            continue;
        }
        c->fd = cfd;
        atomic_init(&c->bytes_received, 0);

        if (pthread_create(&c->tid, NULL, handle_client, c) != 0) {
            perror("pthread_create");
            close(cfd);
            free(c);
            return EXIT_FAILURE;
        }
    }

    logmsg("[server] todas as conexoes aceitas, aguardando nomes...\n");

    /* Espera as N threads chegarem na barreira (todas leram o nome). */
    pthread_barrier_wait(&g_start_barrier);

    logmsg("[server] enviando GO para os %d clientes...\n",
           g_num_registered);

    /*
     * Envia GO para todos. Depois marca t0.
     * Ordem: GO -> t0 -> threads comecam a receber.
     * Como as threads ja passaram pela barreira, elas estao bloqueadas
     * em recv(), esperando os primeiros bytes. Os clientes so enviarao
     * depois de receber GO. Entao t0 marcado logo apos enviar GOs eh
     * uma aproximacao razoavel do inicio real da transmissao.
     */
    for (int i = 0; i < g_num_registered; i++) {
        if (send_all(g_clients[i]->fd, "GO\n", 3) == -1) {
            fprintf(stderr, "[server] falha ao enviar GO para %s\n",
                    g_clients[i]->name);
        }
    }

    clock_gettime(CLOCK_MONOTONIC, &g_t_start);
    g_measurement_active = 1;

    /* Dispara amostradora. */
    pthread_t sampler_tid;
    if (pthread_create(&sampler_tid, NULL, sampler, NULL) != 0) {
        fprintf(stderr, "[server] pthread_create sampler falhou\n");
    }

    logmsg("[server] medicao iniciada (duracao combinada: %d s).\n",
           g_duration_s);

    /* Espera todas as threads de cliente terminarem. */
    for (int i = 0; i < g_num_registered; i++) {
        pthread_join(g_clients[i]->tid, NULL);
    }

    struct timespec t_end;
    clock_gettime(CLOCK_MONOTONIC, &t_end);

    /* Encerra amostradora. */
    g_measurement_active = 0;
    pthread_join(sampler_tid, NULL);

    compute_and_report(&t_end);

    /* Limpeza. */
    for (int i = 0; i < g_num_registered; i++) {
        close(g_clients[i]->fd);
        free(g_clients[i]);
    }
    pthread_barrier_destroy(&g_start_barrier);
    pthread_mutex_destroy(&g_register_mutex);
    close(server_fd);

    return EXIT_SUCCESS;
}