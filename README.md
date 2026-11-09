# Chat TCP Throughput

Medição da taxa de transmissão agregada de um servidor TCP com 1 a 10
clientes simultâneos, a partir de uma aplicação de chat multithread.

## Estrutura do repositório

```
tcp-throughput-chat/
├── original/           # Chat TCP original fornecido pelo professor,
│   ├── chat_server.c   # mantido sem modificação como ponto de partida
│   ├── chat_client.c
│   └── chat_example
├── src/                # Versão instrumentada para medir vazão
│   ├── chat_server.c
│   ├── chat_client.c
│   └── chat_example
├── docs/               # Relatório em LaTeX (template SBC)
│   ├── sbc-template.tex
│   ├── sbc-template.pdf
│   └── figs/
└── README.md
```

## Compilação

A partir de `src/`:

```bash
gcc -Wall -Wextra -O2 -pthread chat_server.c -o chat_server
gcc -Wall -Wextra -O2 -pthread chat_client.c -o chat_client
```

Requer Linux com `glibc` e suporte a `pthread`. Testado com `gcc` 11+.

## Execução

### Servidor

```bash
./chat_server -p <porta> -n <N> -d <duracao_s> [opcoes]
```

O servidor espera exatamente `N` conexões TCP antes de começar a medir. A
rodada termina quando todos os clientes fecham a conexão (FIN detectado
via `recv == 0`).

**Opções:**

| Flag | Padrão | Descrição |
|------|--------|-----------|
| `-p <porta>` | — | Porta TCP (obrigatória) |
| `-n <N>` | — | Número de clientes esperados (obrigatório, 1–64) |
| `-d <s>` | — | Duração da rodada em segundos (obrigatória) |
| `-o <arquivo>` | `results.csv` | CSV de resumo (append) |
| `-s <arquivo>` | `samples.csv` | CSV de amostras por segundo (append) |
| `-r <id>` | `0` | Identificador da repetição |
| `-b <bytes>` | `65536` | Tamanho do bloco combinado com o cliente (só registro) |
| `-w <s>` | `5` | Segundos de warmup descartados da janela estável |
| `-c <s>` | `5` | Segundos de cooldown descartados da janela estável |
| `-l <label>` | `""` | Rótulo da campanha (`loopback`, `lan`, …) |
| `-q` | — | Modo silencioso (nada no stdout) |

Exemplo:

```bash
./chat_server -p 5000 -n 5 -d 30 -l lan -r 1
```

### Cliente

```bash
./chat_client <IP_servidor> <porta> <duracao_s> <num_clientes>
```

O cliente cria `num_clientes` threads internas, cada uma estabelecendo
sua própria conexão TCP com o servidor e transmitindo blocos de 64 KiB
preenchidos com `'A'` durante `duracao_s` segundos.

Exemplo:

```bash
./chat_client 127.0.0.1 5000 30 5
```

### Ordem de execução

1. Sobe o servidor primeiro — ele bloqueia esperando as `N` conexões.
2. Dispara o cliente apontando para o IP do servidor, com o mesmo `N` e
   a mesma duração.
3. O servidor marca `t0` quando todos os clientes terminam de enviar o
   nome, mede, e grava uma linha em `results.csv` quando a rodada acaba.
