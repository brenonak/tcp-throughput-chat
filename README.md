# Chat TCP Throughput

Experimentos de vazao agregada recebida por um servidor TCP com 1 a 10 conexoes simultaneas. Cada conexao corresponde a uma thread do programa cliente. Nao sao necessarios dez computadores.

## Preparacao no Ubuntu ou WSL

Execute os comandos Linux no terminal Ubuntu, na raiz deste repositorio:

```bash
sudo apt update
sudo apt install build-essential python3-venv iproute2 ethtool
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
make
make test
```

Os binarios ficam em `build/`. Flags: `-O2 -Wall -Wextra -pthread`. Os fontes originais permanecem em `original/`. A analise precisa das bibliotecas Python; compilacao, execucao e validacao dos CSVs usam apenas ferramentas do sistema e a biblioteca padrao Python.

## Piloto e campanha em loopback

```bash
bash scripts/run_experiments.sh loopback --machine-id pc_a --clients 1,10 --repetitions 1 --duration 15 --warmup 2 --cooldown 2 --output results/piloto_pc_a
bash scripts/run_experiments.sh loopback --machine-id pc_a --clients 1,2,3,4,5,6,7,8,9,10 --repetitions 2 --duration 15 --warmup 2 --cooldown 2 --output results/campanha_curta_pc_a
bash scripts/run_experiments.sh loopback --machine-id pc_a --output results/loopback_pc_a
```

Padrao: N de 1 a 10 em ordem crescente, dez repeticoes por N, 30 segundos, bloco fixo de 65.536 bytes, descartes de cinco segundos no inicio e no fim e intervalo de cinco segundos entre rodadas. Aproximadamente uma hora por campanha. Os parametros podem ser consultados com `bash scripts/run_experiments.sh --help`. O diretorio de saida deve ser novo.

Use um ID estavel para cada maquina, por exemplo `pc_a` e `pc_b`. Sem `--machine-id`, o ID e o hostname. Para executar loopback na segunda maquina, use `--machine-id pc_b` e outra pasta, como `results/loopback_pc_b`. No loopback, cliente e servidor recebem o mesmo ID. `config.json` registra tambem o hostname e o sistema local; os CSVs consolidados e a analise preservam os IDs de cliente e servidor.

## Dois computadores na rede local

Use a mesma revisao do repositorio nas duas maquinas, com as dependencias instaladas. Computador A executa o servidor; computador B executa todas as conexoes clientes. Os programas C continuam usando a mesma interface em loopback e LAN.

Identifique o IPv4 acessivel do servidor com `ip -4 addr` e a interface com `ip route`. Exemplo: IP 192.168.1.20, interface eth0. Os computadores precisam conseguir se comunicar pela porta TCP 5000. Se houver firewall ativo, configure a liberacao dessa porta para a rede utilizada.

No WSL, o endereco interno pode nao ser acessivel por outra maquina. Valide a conectividade antes da campanha e ajuste a rede do Windows/WSL quando necessario. Uma alternativa e usar Linux nativo para o servidor. Redes Wi-Fi com isolamento entre clientes tambem podem impedir a comunicacao.

No computador A:

```bash
bash scripts/run_experiments.sh server --machine-id pc_a --client-machine-id pc_b --ip 192.168.1.20 --label lan_cabo --interface eth0 --output results/cabo_servidor_pc_a
```

A cada rodada pronta, o executor mostra um comando para executar no computador B, na raiz do repositorio. Por exemplo:

```bash
bash scripts/run_experiments.sh client --machine-id pc_b --server-machine-id pc_a --ip 192.168.1.20 --port 5000 --duration 30 --clients 5 --rep 1 --label lan_cabo --interface eth0
```

Execute somente o comando da rodada atual e espere o servidor indicar a proxima. O modo cliente compila seu binario, coleta seu ambiente e salva um log em um novo diretorio. Para coletar informacoes da interface uma unica vez:

```bash
bash scripts/coleta_ambiente.sh results/ambiente_cliente eth0
```

Copie essa pasta para `results/cabo_servidor_pc_a/ambiente/cliente` no servidor. Preserve tambem as pastas de cada rodada executada no cliente, que contem sua configuracao e monitoramento. Preencha `notas.txt` com cabo, switch/roteador, velocidade ou condicoes de Wi-Fi e outras cargas nas maquinas. Para Wi-Fi, use `--label lan_wifi` e outro diretorio. Mantenha o tipo de conexao fixo durante a campanha. SSH nao e necessario.

Para inverter os papeis, inicie o modo servidor no computador B, usando o IPv4 e a interface dele. Por exemplo:

```bash
bash scripts/run_experiments.sh server --machine-id pc_b --client-machine-id pc_a --ip 192.168.1.21 --label lan_cabo --interface eth0 --output results/cabo_servidor_pc_b
```

Execute os comandos gerados no computador A. Os IDs da outra maquina sao declarados nos argumentos; nao ha verificacao automatica da identidade remota. Assim, as quatro campanhas sao loopback em A, loopback em B, LAN com servidor A e LAN com servidor B. Use os mesmos parametros experimentais nas quatro.

## Protocolo e medicao

1. Cada thread cliente conecta, envia um nome terminado em nova linha e espera `GO\n`.
2. O servidor espera todos os N nomes completos, marca t0 com CLOCK_MONOTONIC, prepara a amostradora e libera a recepcao.
3. O servidor envia `GO\n` a todas as conexoes. Cada cliente inicia seu cronometro monotonic e transmite continuamente.
4. Ao terminar o intervalo, os clientes fecham as conexoes. O servidor espera o fim de todas, calcula a vazao e salva os CSVs.

Atualize cliente e servidor juntos. As versoes antigas sem GO sao incompativeis. Nao e necessario sincronizar os relogios das maquinas. GO coordena a partida, mas nao chega exatamente ao mesmo tempo a todas as conexoes. O descarte inicial reduz esse efeito.

O servidor conta apenas carga util recebida, excluindo nomes e controle. A formula principal e:

`Mbps = 8 * bytes_window / (window_s * 1.000.000)`

As amostras sao cumulativas por segundo. A janela usa a diferenca entre o contador no fim e no inicio dos descartes. Sua duracao efetiva esta em `window_s`; nao se presume exatamente 20 segundos. A amostragem depende do escalonamento do sistema. Um send bloqueado pode ultrapassar a duracao solicitada; o executor aplica um prazo externo.

## Saidas e falhas

Cada campanha guarda configuracao, ambiente, ordem implicita das rodadas por N e repeticao, comandos do servidor, logs e CSVs brutos por rodada. `manifest.csv` registra todas as tentativas e os motivos de falha. Apenas rodadas validadas entram nos CSVs consolidados. `duration_s` no resumo e o tempo efetivamente medido pelo servidor; a duracao solicitada esta em config.json.

O executor espera ate 60 segundos pelos clientes e, apos START, ate duracao + 30 segundos pela conclusao. No loopback nao abre conexao de sondagem. Para na primeira falha e preserva os dados. Ctrl+C encerra somente os processos locais que criou. Na LAN, interrompa tambem o comando no outro computador se necessario. Uma nova execucao cria outra campanha.

A coleta apenas consulta o sistema. Comandos ausentes ou sem permissao ficam registrados. O cliente nao informa os bytes enviados; por isso a validacao verifica os dados recebidos, sem comprovar igualdade entre envio e recepcao nem identificar toda desconexao individual antecipada.

## Monitoramento de CPU e rede

O executor coleta automaticamente contadores Linux de `/proc` aproximadamente a cada segundo, em uma thread Python. Usa apenas a biblioteca padrao, sem alterar os programas C. O ultimo intervalo pode ser menor que um segundo. A configuracao da coleta fica em `config.json`.

No servidor e no loopback, cada pasta em `rodadas/` recebe `cpu.csv` e `network.csv`. No modo cliente LAN, esses arquivos ficam na pasta de saida do proprio cliente. Cada linha identifica maquina, papel, N, repeticao, horario UTC, tempo desde o inicio local do monitor e duracao real do intervalo.

- `cpu.csv`: utilizacao geral (`name=cpu`), por processador logico (`cpu0`, `cpu1`, etc.) e dos processos locais cliente/servidor. `scope` distingue sistema de processo. Para processos, 100% equivale a um processador logico ocupado; programas com varias threads podem superar 100%. Amostras de processos ja encerrados ficam ausentes.
- `network.csv`: bytes recebidos/enviados, Mbps, erros e descartes em cada intervalo. Os valores sao diferencas dos contadores da interface. Incluem trafego de outros programas e cabecalhos conforme contabilizados pela interface. Nao equivalem a carga util medida pelo servidor nem medem retransmissoes TCP.
- `monitoring_warnings.txt`: criado se houver falhas de coleta ou interface ausente. Uma falha do monitor nao invalida automaticamente a medicao de vazao; confira os avisos antes de usar as metricas.

Loopback monitora `lo` por padrao. Na LAN, `--interface` seleciona a interface local; sem esse argumento, todas sao registradas. Acrescente `--interface` ao comando gerado para o cliente usando o nome da interface dele, que pode diferir do servidor. No WSL2, os contadores sao das interfaces e processadores visiveis ao Linux.

A coleta cobre a vida da rodada, incluindo espera por conexoes e encerramento. `elapsed_s` comeca no monitor local, sem sincronizacao com `GO` ou com o outro computador. Para comparar custos, mantenha o monitoramento igual nas campanhas. `--no-monitor` desativa a coleta e e propagado ao comando cliente LAN, permitindo um piloto para avaliar seu impacto. Os novos CSVs ficam disponiveis para discutir gargalos; `analyze.py` continua gerando os graficos de vazao.

## Analise

Com o ambiente Python ativado:

```bash
python3 scripts/analyze.py results/loopback_pc_a --output results/loopback_pc_a/analise
python3 scripts/analyze.py results/loopback_pc_a results/loopback_pc_b results/cabo_servidor_pc_a results/cabo_servidor_pc_b --output results/comparacao
```

O diretorio de analise deve estar vazio ou nao existir. Campanhas com duracoes, blocos ou descartes diferentes sao rejeitadas. Cada campanha permanece identificada, mesmo quando usa o mesmo tipo de rede.

Saidas:

- `summary.csv`: quantidade valida, maximo, media, desvio padrao amostral e IC 95% pela distribuicao t.
- `rounds.csv` e `per_client.csv`: valores usados nos graficos, em Mbps decimais.
- `throughput_max`, `throughput_mean` e `per_client`: graficos em PNG e PDF.
- `warnings.txt`: falhas, cenarios ausentes e repeticoes insuficientes.

O grafico obrigatorio e throughput_max: numero de clientes versus maior vazao agregada observada entre as repeticoes validas. Esse maximo nao representa capacidade teorica. A media usa IC de 95%; uma unica repeticao nao fornece desvio ou IC. Valores extremos nao sao removidos e cenarios ausentes nao recebem zero.

A analise revalida os CSVs de cada rodada a partir do manifesto e das amostras originais. Use esses arquivos para discutir variacao, saturacao e limites de CPU, memoria e rede. A redacao do relatorio, iperf3, SSH, varredura de blocos e contagem de envio ficam fora desta versao.
