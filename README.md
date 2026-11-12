# Chat TCP Throughput

Experimentos de vazão agregada recebida por um servidor TCP com 1 a 10 conexões simultâneas, a partir de uma aplicação de chat multithread modificada para geração contínua de carga e medição de *goodput*. Cada conexão corresponde a uma *thread* do programa cliente, dispensando o uso de dez computadores físicos.

## Estrutura do repositório

- `original/`: código-fonte original da aplicação de chat (`chat_server.c` e `chat_client.c`), preservado sem modificações.
- `src/`: versão instrumentada do servidor e do cliente para geração de carga, sincronização de início e medição de vazão.
- `scripts/`: automação das campanhas (`run_experiments.sh`, `experiments.py`), validação de rodadas (`metrics.py`), monitoramento de CPU e rede (`monitoring.py`), coleta de ambiente (`coleta_ambiente.sh`) e geração de estatísticas e gráficos (`analyze.py`).
- `tests/`: testes automatizados do protocolo de sincronização, validação de amostras e cálculo de métricas.
- `docs/`: relatório técnico no formato SBC (`relatorio_tcp_168765_168826_169251.tex`, `relatorio_tcp_168765_168826_169251.pdf` e figuras em `docs/figs/`). Os artefatos temporários de compilação do LaTeX (`.aux`, `.bbl`, `.blg`, `.fdb_latexmk`, `.fls`, `.log`, `.synctex.gz`, entre outros) são ignorados pelo `.gitignore`.
- `results/compartilhados/`: campanhas experimentais validadas (`loopback`, `lan_cabo` e `lan_wifi`), comparativos consolidados e painel completo de análises (`analises_completas_20261111/`).

## Preparação no Ubuntu ou WSL

Execute os comandos Linux no terminal Ubuntu, na raiz deste repositório:

```bash
sudo apt update
sudo apt install build-essential python3-venv iproute2 ethtool
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
make
make test
```

Os binários compilados ficam em `build/`. As *flags* utilizadas são `-O2 -Wall -Wextra -pthread`. A compilação, a execução das campanhas e a validação dos CSVs usam apenas ferramentas do sistema e a biblioteca padrão do Python; o ambiente virtual com `pandas` e `matplotlib` é utilizado por `scripts/analyze.py`.

## Piloto e campanha em loopback

```bash
bash scripts/run_experiments.sh loopback --machine-id pc_a --clients 1,10 --repetitions 1 --duration 15 --warmup 2 --cooldown 2 --output results/piloto_pc_a
bash scripts/run_experiments.sh loopback --machine-id pc_a --clients 1,2,3,4,5,6,7,8,9,10 --repetitions 2 --duration 15 --warmup 2 --cooldown 2 --output results/campanha_curta_pc_a
bash scripts/run_experiments.sh loopback --machine-id pc_a --output results/loopback_pc_a
```

Configuração padrão: $N$ de 1 a 10 em ordem crescente, cinco repetições por $N$ (50 rodadas), 30 segundos por rodada, bloco fixo de 65.536 bytes (64 KiB), descartes de cinco segundos no início e no fim e intervalo de cinco segundos entre rodadas (aproximadamente 30 minutos por campanha). O argumento `--repetitions` permite escolher outra quantidade. Os parâmetros podem ser consultados com `bash scripts/run_experiments.sh --help`. O diretório de saída deve ser novo.

Use um identificador estável para cada máquina (por exemplo, `D15-126` e `ANVS14`, ou `pc_a` e `pc_b`). Sem `--machine-id`, utiliza-se o *hostname*. No *loopback*, cliente e servidor recebem o mesmo identificador. O arquivo `config.json` registra também o *hostname* e o sistema local, enquanto os CSVs consolidados e a análise preservam os identificadores de cliente e servidor.

## Dois computadores na rede local (Ethernet e Wi-Fi)

Use a mesma revisão do repositório nas duas máquinas, com as dependências instaladas. O computador A executa o servidor e o computador B executa todas as conexões clientes. Os programas em C utilizam a mesma interface em *loopback*, rede cabeada (Ethernet) e rede sem fio (Wi-Fi).

Identifique o endereço IPv4 acessível do servidor com `ip -4 addr` e a interface com `ip route` (por exemplo: IP `192.168.1.20`, interface `eth0`). Os computadores precisam se comunicar pela porta TCP 5000. Se houver *firewall* ativo, libere essa porta para a rede utilizada.

No WSL2, valide a conectividade entre as máquinas antes de iniciar a campanha e configure o encaminhamento de rede entre Windows e WSL quando necessário. Redes Wi-Fi com isolamento entre clientes também podem bloquear a comunicação direta.

No computador servidor (A):

```bash
bash scripts/run_experiments.sh server --machine-id pc_a --client-machine-id pc_b --ip 192.168.1.20 --label lan_cabo --interface eth0 --output results/cabo_servidor_pc_a
```

A cada rodada pronta, o executor exibe o comando correspondente para execução no computador cliente (B), na raiz do repositório. Por exemplo:

```bash
bash scripts/run_experiments.sh client --machine-id pc_b --server-machine-id pc_a --ip 192.168.1.20 --port 5000 --duration 30 --clients 5 --rep 1 --label lan_cabo --interface eth0
```

Execute somente o comando da rodada atual e aguarde o servidor indicar a próxima. O modo cliente compila seu binário, coleta seu ambiente e salva o registro da execução em um novo diretório. Para coletar informações da interface do cliente uma única vez:

```bash
bash scripts/coleta_ambiente.sh results/ambiente_cliente eth0
```

Para o cenário sem fio (Wi-Fi), utilize `--label lan_wifi` e outro diretório de saída:

```bash
bash scripts/run_experiments.sh server --machine-id pc_a --client-machine-id pc_b --ip 192.168.1.20 --label lan_wifi --interface eth0 --output results/wifi_servidor_pc_a
```

Mantenha o meio de conexão fixo durante toda a campanha.

## Protocolo e medição

1. Cada *thread* cliente conecta ao servidor, envia seu nome terminado em nova linha e aguarda `GO\n`.
2. O servidor aguarda todos os $N$ nomes completos, registra $t_0$ com `CLOCK_MONOTONIC`, prepara a *thread* amostradora e libera a recepção.
3. O servidor envia `GO\n` a todas as conexões. Cada cliente inicia seu cronômetro monotônico e transmite blocos continuamente.
4. Ao terminar o intervalo, os clientes fecham as conexões. O servidor aguarda o encerramento de todas, calcula a vazão e grava os arquivos CSV.

Não é necessário sincronizar os relógios entre máquinas distintas, pois a medição ocorre integralmente no relógio monotônico do servidor. O descarte inicial (*warmup*) reduz o efeito de eventuais diferenças no instante de chegada do `GO\n` e do crescimento inicial da janela TCP.

O servidor contabiliza apenas a carga útil recebida (*goodput*), excluindo os nomes iniciais, a mensagem de controle e os cabeçalhos TCP/IP/Ethernet. A taxa agregada é calculada por:

`Mbps = 8 * bytes_window / (window_s * 1.000.000)`

As amostras são cumulativas, com coleta programada a cada segundo. `tick_s` identifica o segundo programado e `elapsed_s` registra, com `CLOCK_MONOTONIC`, o instante real ao concluir a leitura dos contadores. Os descartes inicial e final selecionam os *ticks* da janela estável (`window_s`), cuja duração efetiva é dada pela diferença entre os respectivos `elapsed_s` (ou desde $t_0$ quando `warmup=0`).

## Saídas e compartilhamento

Cada campanha armazena configuração (`config.json`), dados de ambiente, manifesto de execução (`manifest.csv`), logs e CSVs brutos por rodada (`results.csv` e `samples.csv`). Apenas rodadas validadas entram nos CSVs consolidados.

Para versionar resultados pelo Git, utilize `--output results/compartilhados/<campanha>`. Essa pasta é permitida pelo `.gitignore`, enquanto as demais pastas em `results/` permanecem ignoradas localmente.

## Monitoramento de CPU e rede

O executor coleta automaticamente contadores Linux de `/proc` aproximadamente a cada segundo, em uma *thread* Python, usando apenas a biblioteca padrão:

- `cpu.csv`: utilização geral (`name=cpu`), por processador lógico (`cpu0`, `cpu1`, etc.) e dos processos locais cliente/servidor (`scope=process`, em que 100% equivale a um processador lógico ocupado).
- `network.csv`: bytes recebidos/enviados, taxa em Mbps, erros e descartes por intervalo na interface monitorada (`lo` no *loopback*, ou a interface indicada por `--interface` na LAN).
- `monitoring_warnings.txt`: gerado caso ocorram avisos de leitura ou interface ausente.

O argumento `--no-monitor` desativa a coleta caso se deseje executar rodadas sem monitoramento.

## Análise e geração de gráficos

Com o ambiente virtual Python ativado:

```bash
python3 scripts/analyze.py results/loopback_pc_a --output results/loopback_pc_a/analise
python3 scripts/analyze.py \
  results/compartilhados/final_loopback_D15-126_20261111_112526 \
  results/compartilhados/final_lan_cabo_D15-126_20261111_103930 \
  results/compartilhados/final_lan_wifi_D15-126_20261111_093652 \
  --output results/comparacao
```

Saídas geradas por `scripts/analyze.py`:

- `summary.csv`: quantidade de rodadas válidas, máximo, média, desvio padrão amostral e intervalo de confiança de 95% (distribuição $t$).
- `rounds.csv` e `per_client.csv`: valores por rodada e por conexão individual, em Mbps decimais.
- `throughput_max`, `throughput_mean` e `per_client`: gráficos em PNG e PDF.
- `warnings.txt`: registro de falhas, cenários ausentes ou repetições insuficientes.

Além disso, o diretório `results/compartilhados/analises_completas_20261111/` contém uma suíte complementar de análise e visualização (`gerar_analises.py` e `index.html`) que consolida as quatro campanhas finais (200 rodadas e 1.100 observações de conexões), gerando tabelas adicionais de equidade (índice de Jain), ganho relativo, variabilidade temporal e dez figuras em PNG, PDF e SVG.

## Síntese dos resultados e discussões

Os experimentos finais foram conduzidos entre as máquinas `D15-126` (servidor, Intel Core i5-12500H) e `ANVS14` (cliente, Intel Core Ultra 7 256V), ambas sob Ubuntu 26.04 em WSL2, com $N$ de 1 a 10 clientes simultâneos e 5 repetições de 30 s por valor de $N$:

- **Rede local cabeada (Ethernet, 1 Gbps):** a vazão agregada média cresceu de 202,9 Mbps ($N=1$) para 743,6 Mbps ($N=3$) e estabilizou em torno de **941 Mbps** a partir de $N=4$ (máximo de 941,6 Mbps). Assim, a transmissão por cabo chegou aproximadamente ao limite físico do cabo, pois o cabo utilizado é de 1 Gbps. Descontada a sobrecarga dos cabeçalhos Ethernet, IP e TCP e do espaçamento entre quadros (com MTU de 1492 bytes no ambiente WSL2), o limite teórico de vazão útil (*goodput*) do enlace de 1 Gbps é de cerca de 941 Mbps. Logo, a partir de quatro clientes, o gargalo passou a ser o próprio limite físico do cabo.
- **Rede local sem fio (Wi-Fi):** a vazão agregada média permaneceu entre **61,2 e 81,4 Mbps** (máximo de 91,6 Mbps em $N=9$), sem ganho sistemático com o aumento de clientes, pois o meio sem fio compartilhado já estava saturado desde $N=1$.
- **Loopback (`D15-126`):** sem limitação de enlace físico de rede, a vazão agregada atingiu média de **176,3 Gbps** (máximo de 180,8 Gbps) com $N=5$ clientes e reduziu-se para 143,4 Gbps em $N=10$ devido à contenção de processador, trocas de contexto e compartilhamento de núcleos entre as *threads* de cliente e servidor na mesma máquina.

O relatório completo com a descrição da arquitetura, metodologia, resultados e discussões encontra-se em `docs/relatorio_tcp_168765_168826_169251.tex` (`docs/relatorio_tcp_168765_168826_169251.pdf`).
