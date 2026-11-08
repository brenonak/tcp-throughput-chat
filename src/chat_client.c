
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <time.h>
#include <pthread.h>
#include <signal.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <netinet/in.h>

#define BUFFER_SIZE 65536 //tamanho teórico máximo IP/TCP

//parametros globais de conexao e tempo (somente leitura pelas threads)
struct sockaddr_in server_addr;
int duration;

int send_all(int fd, const char *data, size_t len) {
    size_t sent = 0;

    while (sent < len) {
        ssize_t n = send(fd, data + sent, len - sent,
                         MSG_NOSIGNAL);

        if (n == -1) {
            if (errno == EINTR)
                continue;
            return -1;
        }

        if (n == 0)
            return -1;

        sent += (size_t)n;
    }

    return 0;
}

void *client_thread(void *arg) {
    int id = *(int *)arg;
    char name[32];
    char buffer[BUFFER_SIZE];

    int sockfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sockfd == -1) {
        perror("socket");
        return NULL;
    }

    if (connect(sockfd, (struct sockaddr *)&server_addr, sizeof(server_addr)) == -1) {
        perror("connect");
        close(sockfd);
        return NULL;
    }

    //envio do identificador para registro da sessao no servidor
    snprintf(name, sizeof(name), "cliente_%d\n", id);
    if (send_all(sockfd, name, strlen(name)) == -1) {
        perror("send");
        close(sockfd);
        return NULL;
    }

    //inicializa o payload fora do laço para evitar overhead de CPU */
    memset(buffer, 'A', sizeof(buffer));

    time_t start = time(NULL);

    //transmissao continua de blocos brutos durante a janela de teste */
    while (time(NULL) - start < duration) {
        //envio direto de blocos, sem o laço do send_all() e sem checagem de "/quit"
        ssize_t n = send(sockfd, buffer, sizeof(buffer), MSG_NOSIGNAL); 


        if (n == -1) {
            if (errno == EINTR)
                continue;
            perror("send");
            break;
        }

        if (n == 0)
            break;
    }

    close(sockfd);
    return NULL;
}

int main(int argc, char *argv[]) {
    if (argc != 5) {
        fprintf(stderr, "Uso: %s <IP> <porta> <duracao_seg> <num_clientes>\n", argv[0]);
        return EXIT_FAILURE;
    }

    int port = atoi(argv[2]);
    duration = atoi(argv[3]);
    int num_clients = atoi(argv[4]);

    if (duration <= 0 || num_clients <= 0) {
        fprintf(stderr, "Duracao e numero de clientes devem ser maiores que zero segundos.\n");
        return EXIT_FAILURE;
    }

    signal(SIGPIPE, SIG_IGN);

    memset(&server_addr, 0, sizeof(server_addr));
    server_addr.sin_family = AF_INET;
    server_addr.sin_port = htons(port);

    if (inet_pton(AF_INET, argv[1],
                  &server_addr.sin_addr) != 1) {
        fprintf(stderr, "Endereco IPv4 invalido.\n");
        return EXIT_FAILURE;
    }

    pthread_t threads[num_clients];
    int ids[num_clients];

    for (int i = 0; i < num_clients; i++) {
        ids[i] = i + 1;
        if (pthread_create(&threads[i], NULL, client_thread, &ids[i]) != 0) {
            fprintf(stderr, "Erro ao criar thread do cliente %d.\n", ids[i]);
            return EXIT_FAILURE;
        }
    }

    for (int i = 0; i < num_clients; i++) {
        pthread_join(threads[i], NULL);
    }

    return EXIT_SUCCESS;
}