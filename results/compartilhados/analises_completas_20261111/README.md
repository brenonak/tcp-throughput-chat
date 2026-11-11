# Análises completas — 11/11/2026

Abra **[index.html](index.html)** no navegador para ver todas as figuras. Consulte **[PLANO.md](PLANO.md)** para as análises realizadas e os próximos passos e **[RESULTADOS.md](RESULTADOS.md)** para os números principais e as limitações.

- Quatro cenários finais: loopback nas duas máquinas, cabo e Wi-Fi.
- 200 rodadas revalidadas e 1.100 observações de conexões.
- Dez figuras, cada uma em PNG (2240 × 1440), PDF vetorial e SVG.
- Gráficos conjuntos em escala logarítmica e detalhes em painéis com escalas próprias, sem ocultar o loopback.
- CSVs com médias, máximos, mediana, IC de 95%, dispersão, ganho, equidade, variação temporal e CPU.
- Fontes relativas, parâmetros e hashes em `dados/proveniencia.json`.

## Reproduzir no Windows

Na raiz do repositório:

```powershell
python results/compartilhados/analises_completas_20261111/gerar_analises.py
```

Usa apenas a biblioteca padrão Python e a validação existente em `scripts/metrics.py`. Não precisa de WSL, pandas ou nova coleta. A renderização PNG usa `System.Drawing` do Windows via `renderizar_png.ps1`. SVG e PDF são produzidos pelo próprio gerador. O comando atualiza somente os arquivos gerados nesta pasta. Os coeficientes t de 95% estão explícitos no código; as campanhas selecionadas exigem cinco repetições completas por N.

Em outros sistemas, o mesmo Python gera os dados, SVG e PDF; a geração PNG automática está disponível somente no Windows. `graficos/primitivas.json` contém as instruções de desenho usadas pelo renderizador PNG.

## Escolha de figuras

Para o artigo, começar por `conjunto_maximo_log.pdf`, `paineis_media.pdf` e `loopbacks_media.pdf`. Para variabilidade e divisão da banda, usar `variabilidade.pdf` e `equidade.pdf`. O máximo é observado entre cinco repetições e não representa uma capacidade teórica.
