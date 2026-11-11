# Plano de análises para ampliar o trabalho

## Base e escopo

A comparação anterior reunia três campanhas com servidor D15-126. Esta pasta acrescenta o loopback ANVS14, formando quatro cenários finais compatíveis: loopback D15-126, loopback ANVS14, cabo e Wi-Fi. Nas duas LANs, ANVS14 é cliente e D15-126 é servidor. São 200 rodadas, com cinco repetições para cada N de 1 a 10, duração solicitada de 30 s, descartes inicial/final de 5 s, bloco de 65.536 bytes e amostragem monotônica.

Os dados do cliente ANVS14 nas LANs contêm monitoramento complementar. Contá-los como outras medições de vazão duplicaria as rodadas. Não há medição final com os papéis LAN invertidos. Campanhas antigas e pilotos têm parâmetros distintos e devem receber análises separadas.

## Análises já realizadas nesta pasta

| Prioridade | Pergunta para o trabalho | Material produzido | Uso sugerido |
|---|---|---|---|
| Alta | Como os quatro cenários se comparam? | `conjunto_maximo_log` e `conjunto_media_log` | Visão geral dos resultados, incluindo ANVS14; máximo observado e média com IC de 95%. |
| Alta | Como ver os detalhes sem o loopback achatar as LANs? | `paineis_maximo` e `paineis_media` | Figura com quatro painéis lineares e escalas independentes explicitadas. Wi-Fi também ganha sua própria escala. |
| Alta | O loopback se comporta da mesma forma nas duas máquinas? | `loopbacks_media` e `comparacao_razoes.csv` | Comparação direta na mesma escala, N de melhor média, queda após o pico e razão ANVS14/D15 por N. |
| Alta | Acrescentar conexões ainda aumenta a vazão? | `ganho_conexoes` e `resumo.csv` | T(N)/T(1), eficiência relativa e discussão de saturação; separar ganho agregado de vazão por conexão. |
| Alta | Os resultados são estáveis entre repetições? | `variabilidade`, média e IC, desvio padrão e mediana no CSV | Mostrar CV por N e cenário, sem remover extremos e sem inferir significância apenas pelos ICs. |
| Média | Como a banda é dividida entre conexões? | `equidade`, `vazao_por_conexao`, `equidade_por_rodada.csv`, `conexoes.csv` | Índice de Jain por rodada e razão menor/maior conexão. T(N)/N mostra a média, mas não substitui a medida de equidade. |
| Média | A vazão oscila dentro da janela útil? | `variacao_temporal` e `estabilidade_temporal.csv` | CV dos incrementos dos contadores dividido pelos intervalos reais; resumido entre rodadas. |
| Média | Quais dados de CPU existem no ANVS14 e no D15? | `cpu_por_rodada.csv` | Médias ponderadas separadas por máquina, papel e processo, incluindo ANVS14 cliente nas LANs. Base para investigação exploratória. |

Cada nome de figura corresponde a arquivos PNG, PDF vetorial e SVG dentro de `graficos/`. Os CSVs estão em `dados/`. A galeria está em `index.html`; os números principais e as limitações estão em `RESULTADOS.md`.

## Próximas análises com os dados já disponíveis

1. **CPU e vazão, com controle do escopo temporal.** Produzir gráficos por N da CPU do sistema e dos processos, separando cliente e servidor. A tabela preparada usa a coleta inteira, não a janela útil: primeiro avaliar o deslocamento entre início do monitor e GO nos logs. Se não houver referência recuperável, manter os gráficos como descrição da rodada inteira. Uma associação CPU/vazão não identifica sozinha o gargalo; usar também a distribuição por processador lógico, disponível nos CSVs originais.
2. **Janela efetiva e sensibilidade no Wi-Fi.** Relacionar `window_s` e vazão por rodada; comparar, quando houver ticks suficientes, uma janela fixa comum de 20 s após o descarte inicial com a janela original. Revalidar os contadores e explicitar a mudança de estimando. Quantificar quanto as conclusões mudam com os intervalos de encerramento mais longos.
3. **Evolução temporal representativa.** Mostrar as cinco séries de intervalos, em painéis para N=1, N do pico de média e N=10. Isso ajuda a distinguir rajadas de instabilidade persistente sem escolher apenas uma rodada conveniente. O resumo temporal desta pasta já permite selecionar os casos por regra explícita.
4. **Influência de extremos.** Contrastar média, mediana e máximo para cada N. Refazer descritivamente a média deixando uma repetição de fora a cada vez e registrar a faixa obtida, sem descartar observações na análise principal. Isso avalia a sensibilidade dos picos com apenas cinco repetições.
5. **Interface e carga útil.** Examinar erros/descartes e contadores de rede de ambos os lados. Os monitores não estão sincronizados ao GO; evitar calcular uma suposta eficiência de protocolo dividindo médias de janelas diferentes. No WSL, interface virtual também não representa diretamente o enlace físico. Os arquivos não fornecem contagem de retransmissões TCP.
6. **Ordem e possível deriva.** Usar os horários dos manifestos para verificar tendência ao longo da coleta. Como N cresce com o tempo, concorrência e deriva temporal estão confundidas: a análise pode apontar esse limite, mas não eliminá-lo.

## Novas coletas necessárias para conclusões mais fortes

| Coleta | Motivo | Desenho sugerido |
|---|---|---|
| LAN com servidor ANVS14 e cliente D15-126 | Separar direção e papel das máquinas | Cabo e Wi-Fi, mesmos parâmetros, N=1 a 10, pelo menos cinco repetições. Comparar cada direção separadamente. |
| Repetir blocos em ordem aleatória de N | Reduzir confusão com aquecimento e condições que variam no tempo | Randomizar N dentro de cada bloco e registrar a semente, mantendo todas as condições e o monitoramento. |
| Repetir em outros dias e condições de Wi-Fi | Avaliar generalização e variabilidade entre campanhas | Registrar banda, canal, distância, sinal, alimentação e carga concorrente; tratar cada campanha como unidade própria. |
| Comparar WSL e Linux nativo e usar referência de rede | Investigar hipóteses sobre encaminhamento e processamento | Comparação controlada, mesmo hardware e enlace, com parâmetros e direção equivalentes; não atribuir as diferenças atuais a um único componente. |

## Ordem sugerida para incorporar ao texto

1. Atualizar a tabela de resultados para quatro cenários, preservando identidade e direção.
2. Abrir os resultados com máximo logarítmico; usar a média em painéis para discussão detalhada.
3. Criar uma subseção comparando os dois loopbacks, incluindo picos, ganho e limites de atribuição causal.
4. Acrescentar estabilidade e equidade à discussão de cabo e Wi-Fi.
5. Encerrar com limites de janela, ordem da coleta e ausência de inversão dos papéis, distinguindo observações de hipóteses.

Os arquivos do artigo e as análises anteriores foram preservados. Esta pasta é material complementar para revisão e escolha das figuras que entrarão na versão final.
