# Resultados adicionais

Base: quatro campanhas finais compatíveis, 50 rodadas cada (N=1 a 10, cinco repetições), total de 200 rodadas revalidadas a partir dos CSVs brutos.

| Cenário | Melhor média (Mbps) | N da melhor média | Máximo observado (Mbps) | Ganho N=10 / N=1 |
|---|---:|---:|---:|---:|
| Loopback D15-126 | 176293.553 | 5 | 180762.126 | 2.90× |
| Loopback ANVS14 | 268136.136 | 8 | 271766.084 | 3.52× |
| Cabo ANVS14 → D15-126 | 941.149 | 8 | 941.630 | 4.64× |
| Wi-Fi ANVS14 → D15-126 | 81.371 | 2 | 91.620 | 1.11× |

## Como interpretar

- Os gráficos conjuntos logarítmicos permitem ver as quatro séries. Os painéis mostram os detalhes em escalas lineares próprias; não compare alturas entre painéis sem ler os eixos. Não há valores ocultos nem eixo interrompido.
- A comparação entre loopbacks usa uma única escala linear para comparar ANVS14 e D15-126 diretamente. Diferenças incluem hardware, sistema, kernel, WSL e condições da coleta; não isolam o efeito de cada componente.
- Ganho relativo é T(N)/T(1), calculado a partir das médias. Eficiência é esse ganho dividido por N (CSV). São razões descritivas; não foram calculados ICs para essas razões.
- O CV entre repetições mede dispersão relativa, enquanto o CV temporal descreve os intervalos da janela útil de cada rodada. Intervalos dentro de uma rodada não são tratados como repetições independentes. O CV temporal não é ponderado pela duração dos intervalos e é sensível aos atrasos da amostragem.
- Jain é calculado por rodada com as vazões individuais na mesma janela: (soma x)² / (N × soma x²). Com N=1 ele vale 1 por definição. Os ICs t são apresentados sem truncamento e podem ultrapassar os limites físicos do índice ou apresentar limites negativos para CV; isso é uma limitação da aproximação, não uma observação negativa.
- As médias têm IC t de 95% (desvio padrão amostral, cinco rodadas, 4 graus de liberdade). São intervalos descritivos sob a hipótese de independência. Ordem crescente de N, poucas repetições e possível autocorrelação limitam inferências; sobreposição de IC não é teste de igualdade.
- Máximo significa o maior valor observado em cinco rodadas, não capacidade teórica. Valores extremos foram preservados.
- Monitoramento de CPU inclui a vida inteira da coleta local, com espera e encerramento; os tempos não estão alinhados ao GO. O CSV usa média ponderada por interval_s e separa CPU total, processos, máquinas e papéis. CPU total é percentual da máquina; em processo, 100% equivale a um processador lógico e pode ser excedido. Não usar como prova causal de gargalo.
- Os registros do ANVS14 cliente em cabo/Wi-Fi complementam o monitoramento; não são outras campanhas de vazão. A carga útil recebida é medida somente pelo servidor. Não há LAN com ANVS14 como servidor nesses dados finais.
- Pilotos de 15 segundos, tentativas falhas e campanhas antigas com amostragem nominal não foram misturados com as finais de 30 segundos e amostragem monotônica.

## Rastreabilidade

Consulte `dados/proveniencia.json`: fontes relativas ao repositório, parâmetros, IDs, arquivos consumidos e SHA-256 combinado (nome relativo + conteúdo, em ordem de caminho). `dados/avisos.txt` registra falhas ou ausências. Os CSVs preservam cenário, N e repetição. Não foi realizada nova coleta de rede.
