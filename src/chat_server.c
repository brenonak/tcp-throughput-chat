
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

#define BUFFER_SIZE 1024
#define MAX_CLIENTS 100

typedef struct Client {
    int fd;
    char name[32];
    struct Client *next;
} Client;

Client *clients = NULL;
int num_clients = 0;

pthread_mutex_t clients_mutex = PTHREAD_MUTEX_INITIALIZER;

/* Envia todos os bytes, mesmo se send() enviar parcialmente. */
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

/* Le uma linha terminada por '\n'. */
ssize_t read_line(int fd, char *buffer, size_t capacity) {
    size_t pos = 0;

    while (pos < capacity - 1) {
        char c;
        ssize_t n = recv(fd, &c, 1, 0);

        if (n == 0)
            return pos == 0 ? 0 : (ssize_t)pos;

        if (n == -1) {
            if (errno == EINTR)
                continue;
            return -1;
        }

        if (c == '\n')
            break;

        if (c != '\r')
            buffer[pos++] = c;
    }

    buffer[pos] = '\0';
    return (ssize_t)pos;
}

/* Distribui uma mensagem aos demais clientes. */
void broadcast(const char *message, Client *sender) {
    pthread_mutex_lock(&clients_mutex);

    Client *current = clients;

    while (current != NULL) {
        if (current != sender) {
            if (send_all(current->fd, message,
                         strlen(message)) == -1) {
                fprintf(stderr,
                        "Falha ao enviar para %s.\n",
                        current->name);
            }
        }

        current = current->next;
    }

    pthread_mutex_unlock(&clients_mutex);
}

void *handle_client(void *arg) {
    Client *client = arg;
    char buffer[BUFFER_SIZE];
    char message[BUFFER_SIZE + 64];
    int registered = 0;

    /* A primeira linha recebida e o nome do usuario. */
    ssize_t n = read_line(client->fd, buffer, sizeof(buffer));

    if (n <= 0 || buffer[0] == '\0') {
        close(client->fd);
        free(client);
        return NULL;
    }

    snprintf(client->name, sizeof(client->name),
             "%s", buffer);

    pthread_mutex_lock(&clients_mutex);

    if (num_clients >= MAX_CLIENTS) {
        pthread_mutex_unlock(&clients_mutex);

        const char *error = "Servidor cheio.\n";
        send_all(client->fd, error, strlen(error));
        close(client->fd);
        free(client);
        return NULL;
    }

    client->next = clients;
    clients = client;
    num_clients++;
    registered = 1;

    pthread_mutex_unlock(&clients_mutex);

    snprintf(message, sizeof(message),
             "*** %s entrou no chat. ***\n",
             client->name);
    broadcast(message, client);

    printf("Usuario conectado: %s\n", client->name);

    while ((n = read_line(client->fd, buffer,
                          sizeof(buffer))) > 0) {
        if (strcmp(buffer, "/quit") == 0)
            break;

        snprintf(message, sizeof(message),
                 "%s: %s\n", client->name, buffer);

        broadcast(message, client);
    }

    if (n == -1)
        perror("recv");

    if (registered) {
        pthread_mutex_lock(&clients_mutex);

        Client **current = &clients;

        while (*current != NULL && *current != client)
            current = &(*current)->next;

        if (*current == client) {
            *current = client->next;
            num_clients--;
        }

        pthread_mutex_unlock(&clients_mutex);

        snprintf(message, sizeof(message),
                 "*** %s saiu do chat. ***\n",
                 client->name);
        broadcast(message, NULL);
    }

    printf("Usuario desconectado: %s\n", client->name);

    close(client->fd);
    free(client);

    return NULL;
}

int main(int argc, char *argv[]) {
    int server_fd;
    struct sockaddr_in server_addr;

    if (argc != 2) {
        fprintf(stderr, "Uso: %s <porta>\n", argv[0]);
        return EXIT_FAILURE;
    }

    int port = atoi(argv[1]);

    signal(SIGPIPE, SIG_IGN);

    server_fd = socket(AF_INET, SOCK_STREAM, 0);

    if (server_fd == -1) {
        perror("socket");
        return EXIT_FAILURE;
    }

    int opt = 1;
    setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR,
               &opt, sizeof(opt));

    memset(&server_addr, 0, sizeof(server_addr));
    server_addr.sin_family = AF_INET;
    server_addr.sin_addr.s_addr = htonl(INADDR_ANY);
    server_addr.sin_port = htons(port);

    if (bind(server_fd, (struct sockaddr *)&server_addr,
             sizeof(server_addr)) == -1) {
        perror("bind");
        close(server_fd);
        return EXIT_FAILURE;
    }

    if (listen(server_fd, 10) == -1) {
        perror("listen");
        close(server_fd);
        return EXIT_FAILURE;
    }

    printf("Chat TCP ativo na porta %d.\n", port);

    while (1) {
        struct sockaddr_in client_addr;
        socklen_t addr_len = sizeof(client_addr);

        int client_fd = accept(
            server_fd,
            (struct sockaddr *)&client_addr,
            &addr_len
        );

        if (client_fd == -1) {
            if (errno == EINTR)
                continue;

            perror("accept");
            continue;
        }

        Client *client = malloc(sizeof(Client));

        if (client == NULL) {
            perror("malloc");
            close(client_fd);
            continue;
        }

        client->fd = client_fd;
        client->name[0] = '\0';
        client->next = NULL;

        pthread_t tid;

        if (pthread_create(&tid, NULL,
                           handle_client, client) != 0) {
            fprintf(stderr, "Erro ao criar thread.\n");
            close(client_fd);
            free(client);
            continue;
        }

        pthread_detach(tid);
    }

    close(server_fd);
    pthread_mutex_destroy(&clients_mutex);

    return EXIT_SUCCESS;
}
