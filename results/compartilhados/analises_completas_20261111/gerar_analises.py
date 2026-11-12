"""Revalida as campanhas finais e gera análises sem dependências Python externas."""
import csv
import hashlib
import html
import json
import math
import os
from pathlib import Path
import statistics as st
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from metrics import IDENTITY, MANIFEST, campaign_identity, read_csv, validate_round

SOURCES = [
    ('Loopback D15-126', 'final_loopback_D15-126_20261111_112526'),
    ('Loopback ANVS14', 'final_loopback_ANVS14_20261111_082703'),
    ('Cabo ANVS14 → D15-126', 'final_lan_cabo_D15-126_20261111_103930'),
    ('Wi-Fi ANVS14 → D15-126', 'final_lan_wifi_D15-126_20261111_093652'),
]
CLIENTS = {
    'lan_cabo': 'final_lan_cabo_ANVS14_cliente_20261111_103947',
    'lan_wifi': 'final_lan_wifi_ANVS14_cliente_20261111_093745',
}
COLORS = ['#2563eb', '#d97706', '#15803d', '#be185d']
OUT = HERE / 'dados'
FIG = HERE / 'graficos'
T95 = {2: 12.7062047364, 3: 4.3026527297, 4: 3.1824463053, 5: 2.7764451052,
       6: 2.5705818356, 7: 2.4469118511, 8: 2.3646242516, 9: 2.3060041352,
       10: 2.2621571629}


def summary(values):
    n = len(values)
    mean = st.mean(values)
    sd = st.stdev(values) if n > 1 else None
    half = T95[n] * sd / math.sqrt(n) if n > 1 else None
    return dict(count=n, mean=mean, maximum=max(values), median=st.median(values),
                std=sd, cv_percent=100*sd/mean if sd is not None and mean else None,
                ci95_low=mean-half if half is not None else None,
                ci95_high=mean+half if half is not None else None)


def save_csv(name, rows):
    with (OUT / name).open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class Drawing:
    """Primitivas comuns a SVG, PDF vetorial e PNG nativo do Windows."""
    def __init__(self, name, title, subtitle):
        self.name = name
        self.commands = []
        self.labels = {}
        self.text(35, 32, title, 23)
        self.text(35, 59, subtitle, 14, '#475569')

    def line(self, x, y, xx, yy, color='#cbd5e1', width=1):
        self.commands.append(dict(kind='line', x=x, y=y, xx=xx, yy=yy, color=color, width=width))

    def text(self, x, y, text, size=13, color='#0f172a'):
        self.commands.append(dict(kind='text', x=x, y=y, text=str(text), size=size, color=color))

    def dot(self, x, y, color):
        self.commands.append(dict(kind='dot', x=x, y=y, color=color))

    def panel(self, series, title, unit, box, log=False, limits=None):
        x, y, w, h = box
        self.text(x, y-33, title, 16)
        self.text(x, y-12, unit, 12, '#475569')
        values = [v for _, _, points in series for _, v, lo, hi in points
                  for v in (v, lo, hi) if v is not None]
        if log:
            assert min(values) > 0, 'Escala log requer valores positivos, inclusive IC'
            lower, upper = math.floor(math.log10(min(values))), math.ceil(math.log10(max(values)))
            ticks = [(k, f'{10**k:g}') for k in range(lower, upper+1)]
            transform = math.log10
        else:
            lower, upper = limits or (min(0, min(values))*1.12, max(values)*1.12 or 1)
            ticks = [(lower+(upper-lower)*k/4, f'{lower+(upper-lower)*k/4:,.2f}'.replace(',', ' ')) for k in range(5)]
            transform = lambda v: v
        px = lambda n: x+(n-1)*w/9
        py = lambda v: y+h-(transform(v)-lower)*h/(upper-lower)
        for value, label in ticks:
            yy = y+h-(value-lower)*h/(upper-lower)
            self.line(x, yy, x+w, yy)
            self.text(x-70, yy+4, label, 11)
        for n in range(1, 11):
            self.text(px(n)-4, y+h+20, n, 12)
        self.text(x+w/2-75, y+h+43, 'Conexões simultâneas (N)', 12)
        for label, color, points in series:
            self.labels[label] = color
            last = None
            for n, value, low, high in points:
                xx, yy = px(n), py(value)
                if last:
                    self.line(*last, xx, yy, color, 2)
                if low is not None:
                    self.line(xx, py(low), xx, py(high), color, 1.2)
                    self.line(xx-4, py(low), xx+4, py(low), color)
                    self.line(xx-4, py(high), xx+4, py(high), color)
                self.dot(xx, yy, color)
                last = (xx, yy)

    def legend(self):
        for i, (label, color) in enumerate(self.labels.items()):
            x, y = 60+(i % 2)*530, 660+(i//2)*23
            self.line(x, y-4, x+25, y-4, color, 3)
            self.text(x+34, y, label, 13)

    def save(self):
        self.legend()
        svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="720" viewBox="0 0 1120 720">',
               '<rect width="1120" height="720" fill="white"/>']
        pdf = ['1 1 1 rg 0 0 1120 720 re f']
        for c in self.commands:
            color = c['color']
            rgb = ' '.join(str(int(color[i:i+2], 16)/255) for i in (1, 3, 5))
            x, y = c['x'], c['y']
            if c['kind'] == 'line':
                svg.append(f'<line x1="{x}" y1="{y}" x2="{c["xx"]}" y2="{c["yy"]}" stroke="{color}" stroke-width="{c["width"]}"/>')
                pdf.append(f'{rgb} RG {c["width"]} w {x} {720-y} m {c["xx"]} {720-c["yy"]} l S')
            elif c['kind'] == 'dot':
                svg.append(f'<circle cx="{x}" cy="{y}" r="3.5" fill="{color}"/>')
                pdf.append(f'{rgb} rg {x-3} {720-y-3} 6 6 re f')
            else:
                svg.append(f'<text x="{x}" y="{y}" font-family="Arial,sans-serif" font-size="{c["size"]}" fill="{color}">{html.escape(c["text"])}</text>')
                # Helvetica / WinAnsi: setas recebem representação ASCII no PDF.
                txt = c['text'].replace('→', '->').encode('cp1252', 'replace').decode('cp1252')
                txt = txt.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
                pdf.append(f'{rgb} rg BT /F1 {c["size"]} Tf {x} {720-y} Td ({txt}) Tj ET')
        (FIG / f'{self.name}.svg').write_text('\n'.join(svg+['</svg>']), encoding='utf-8')
        stream = '\n'.join(pdf).encode('cp1252')
        objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
                   b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1120 720] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
                   b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',
                   f'<< /Length {len(stream)} >>\nstream\n'.encode()+stream+b'\nendstream']
        document = b'%PDF-1.4\n'
        offsets = [0]
        for i, obj in enumerate(objects, 1):
            offsets.append(len(document))
            document += f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
        start = len(document)
        document += b'xref\n0 6\n0000000000 65535 f \n'
        document += b''.join(f'{v:010} 00000 n \n'.encode() for v in offsets[1:])
        document += f'trailer << /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()
        (FIG / f'{self.name}.pdf').write_bytes(document)
        return dict(name=self.name, commands=self.commands)


def main():
    OUT.mkdir(exist_ok=True)
    FIG.mkdir(exist_ok=True)
    rounds, individuals, stats, fairness, temporal, cpu = [], [], [], [], [], []
    provenance, warnings = [], []
    baseline = None
    for scenario, name in SOURCES:
        path = HERE.parent / name
        config = json.loads((path / 'config.json').read_text())
        signature = [config[k] for k in ('duration', 'warmup', 'cooldown', 'block_bytes', 'sample_timing')]
        assert baseline is None or signature == baseline, 'Campanhas incompatíveis'
        baseline = signature
        identity = campaign_identity(config)
        manifest = read_csv(path / 'manifest.csv', MANIFEST, optional_header=IDENTITY)
        used = set()
        digest = hashlib.sha256()
        files = [path / 'config.json', path / 'manifest.csv']
        for attempt in manifest:
            n, rep = int(attempt['n_clients']), int(attempt['rep'])
            if attempt['status'] != 'valid':
                warnings.append(f'{name}: N={n}, rep={rep}: {attempt["reason"]}')
                continue
            assert campaign_identity(attempt) == identity
            assert (n, rep) not in used
            used.add((n, rep))
            directory = path / 'rodadas' / f'n{n:02}_r{rep:03}'
            row, samples, per_client = validate_round(directory, config, n, rep)
            files.extend(directory / f for f in ('results.csv', 'samples.csv'))
            key = dict(scenario=scenario, campaign=name, n_clients=n, rep=rep)
            rounds.append(dict(**key, **identity, mbps=float(row['mbps_window']), window_s=float(row['window_s'])))
            individuals.extend(dict(**key, **value) for value in per_client)
            v = [p['mbps'] for p in per_client]
            fairness.append(dict(**key, jain=sum(v)**2/(n*sum(t*t for t in v)), min_max_ratio=min(v)/max(v)))
            ticks = sorted({int(s['tick_s']) for s in samples})
            begin, end = config['warmup'], max(ticks)-config['cooldown']
            totals = {tick: sum(int(s['bytes_cumulative']) for s in samples if int(s['tick_s']) == tick) for tick in ticks}
            instants = {int(s['tick_s']): float(s['elapsed_s']) for s in samples}
            totals[0], instants[0] = 0, 0
            rates = [(totals[k]-totals[k-1])*8/(instants[k]-instants[k-1])/1e6 for k in range(begin+1, end+1)]
            computed = (totals[end]-totals[begin])*8/(instants[end]-instants[begin])/1e6
            assert abs(computed-float(row['mbps_window'])) < .00051
            temporal.append(dict(**key, intervals=len(rates), interval_cv_percent=100*st.stdev(rates)/st.mean(rates),
                                 interval_min_mbps=min(rates), interval_max_mbps=max(rates)))
            monitors = [('local', directory)]
            if config['label'] in CLIENTS:
                monitors.append(('cliente_remoto', HERE.parent / CLIENTS[config['label']] / f'n{n:02}_r{rep:03}'))
            for origin, monitor in monitors:
                file = monitor / 'cpu.csv'
                if not file.exists():
                    warnings.append(f'Monitoramento ausente: {file.relative_to(ROOT)}')
                    continue
                files.append(file)
                with file.open(newline='') as f:
                    rows = list(csv.DictReader(f))
                for scope, process in sorted({(r['scope'], r['name']) for r in rows if r['scope']=='process' or r['name']=='cpu'}):
                    subset = [r for r in rows if (r['scope'], r['name']) == (scope, process)]
                    assert all(int(r['n_clients'])==n and int(r['rep'])==rep for r in subset)
                    assert all(r['machine_id'] == (identity['client_machine_id'] if origin=='cliente_remoto' else identity['server_machine_id']) for r in subset)
                    weight = sum(float(r['interval_s']) for r in subset)
                    cpu.append(dict(**key, origin=origin, machine_id=subset[0]['machine_id'], scope=scope, process=process,
                                    weighted_cpu_percent=sum(float(r['cpu_percent'])*float(r['interval_s']) for r in subset)/weight,
                                    monitored_s=weight, samples=len(subset)))
        assert used == {(n, r) for n in range(1, 11) for r in range(1, 6)}, f'Campanha incompleta: {name}'
        for file in sorted(files):
            digest.update(str(file.relative_to(ROOT)).replace('\\', '/').encode())
            digest.update(file.read_bytes())
        provenance.append(dict(campaign=name, scenario=scenario, valid_rounds=len(used), sha256_inputs=digest.hexdigest(),
                               input_files=[f.relative_to(ROOT).as_posix() for f in sorted(files)], parameters=dict(zip(('duration','warmup','cooldown','block_bytes','sample_timing'), signature)), **identity))
        for n in range(1, 11):
            values = [r['mbps'] for r in rounds if r['scenario']==scenario and r['n_clients']==n]
            stats.append(dict(scenario=scenario, n_clients=n, **summary(values)))
    for row in stats:
        ref = next(r['mean'] for r in stats if r['scenario']==row['scenario'] and r['n_clients']==1)
        row['speedup_vs_n1'] = row['mean']/ref
        row['efficiency_percent'] = 100*row['speedup_vs_n1']/row['n_clients']
        row['per_connection_mean_mbps'] = row['mean']/row['n_clients']
    comparisons = []
    for n in range(1, 11):
        means = [next(r['mean'] for r in stats if r['scenario']==s and r['n_clients']==n) for s,_ in SOURCES]
        comparisons.append(dict(n_clients=n, loopback_d15_mbps=means[0], loopback_anvs_mbps=means[1],
                                anvs_over_d15=means[1]/means[0], cabo_mbps=means[2], wifi_mbps=means[3], cabo_over_wifi=means[2]/means[3]))
    save_csv('comparacao_razoes.csv', comparisons)
    for name, rows in [('resumo.csv', stats), ('rodadas.csv', rounds), ('conexoes.csv', individuals),
                       ('equidade_por_rodada.csv', fairness), ('estabilidade_temporal.csv', temporal), ('cpu_por_rodada.csv', cpu)]:
        save_csv(name, rows)
    (OUT / 'proveniencia.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / 'avisos.txt').write_text('\n'.join(warnings) if warnings else 'Nenhum aviso: 200 rodadas revalidadas; quatro campanhas completas.\n', encoding='utf-8')

    drawings = []
    def series(metric, ids=range(4), intervals=False, table=stats):
        return [(SOURCES[i][0], COLORS[i], [(r['n_clients'], r[metric], r['ci95_low'] if intervals else None, r['ci95_high'] if intervals else None)
                 for r in table if r['scenario']==SOURCES[i][0]]) for i in ids]
    for metric, suffix, title in [('maximum', 'maximo', 'Máximo observado'), ('mean', 'media', 'Média e IC de 95%')]:
        d = Drawing(f'conjunto_{suffix}_log', f'{title} — quatro cenários', 'Eixo Y logarítmico: intervalos iguais representam razões iguais. Valores em Mbps decimais.')
        d.panel(series(metric, intervals=metric=='mean'), 'Todas as campanhas finais', 'Mbps — escala logarítmica', (115, 135, 945, 445), log=True)
        drawings.append(d.save())
        d = Drawing(f'paineis_{suffix}', f'{title} — detalhes por cenário', 'Escalas Y independentes e lineares, iniciadas em zero. Compare os valores dos eixos entre painéis.')
        for i in range(4):
            d.panel(series(metric, [i], metric=='mean'), SOURCES[i][0], 'Mbps — escala própria', (110+(i%2)*550, 135+(i//2)*260, 425, 160))
        drawings.append(d.save())
    d = Drawing('loopbacks_media', 'Loopback: ANVS14 e D15-126', 'Mesma escala linear; média com IC de 95% entre cinco repetições por N.')
    d.panel(series('mean', [0,1], True), 'Comunicação local nas duas máquinas', 'Mbps', (115, 135, 945, 445))
    drawings.append(d.save())
    for metric, name, title, unit in [('speedup_vs_n1','ganho_conexoes','Ganho relativo ao cenário com uma conexão','T(N) / T(1)'),
                                      ('cv_percent','variabilidade','Variabilidade entre as cinco repetições','CV (%) = 100 × desvio padrão / média'),
                                      ('per_connection_mean_mbps','vazao_por_conexao','Vazão média por conexão','Mbps; média agregada / N')]:
        d = Drawing(name, title, 'Cada painel usa sua própria escala Y linear; todos começam em zero.')
        for i in range(4):
            d.panel(series(metric, [i]), SOURCES[i][0], unit, (110+(i%2)*550, 135+(i//2)*260, 425, 160))
        drawings.append(d.save())
    for raw, metric, name, title, unit, limits in [(fairness, 'jain','equidade','Equidade na divisão da vazão','Índice de Jain (1 = divisão igual)', (0,1.05)),
                                                  (temporal, 'interval_cv_percent','variacao_temporal','Variação da vazão dentro de cada rodada','Média do CV dos intervalos (~1 s), em %',None)]:
        table = [dict(scenario=s, n_clients=n, **summary([r[metric] for r in raw if r['scenario']==s and r['n_clients']==n])) for s,_ in SOURCES for n in range(1,11)]
        save_csv(f'{name}_resumo.csv', table)
        d = Drawing(name, title, 'Média e IC de 95% entre rodadas; valores individuais disponíveis nos CSVs.')
        for i in range(4):
            d.panel(series('mean', [i], True, table), SOURCES[i][0], unit, (110+(i%2)*550, 135+(i//2)*260, 425, 160), limits=limits)
        drawings.append(d.save())
    (FIG / 'primitivas.json').write_text(json.dumps(drawings, ensure_ascii=False), encoding='utf-8')
    if os.name == 'nt':
        subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(HERE/'renderizar_png.ps1')], check=True)
    cards = ''.join(f'<article><h2>{d["name"].replace("_", " ")}</h2><img src="graficos/{d["name"]}.svg" alt="{d["name"]}"><p><a href="graficos/{d["name"]}.pdf">PDF vetorial</a> · <a href="graficos/{d["name"]}.svg">SVG</a> · <a href="graficos/{d["name"]}.png">PNG</a></p></article>' for d in drawings)
    (HERE/'index.html').write_text('<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Análises completas TCP</title><style>body{font:16px system-ui;background:#f1f5f9;color:#0f172a;margin:32px auto;max-width:1150px}article{background:white;padding:20px;margin:24px 0;border-radius:12px}img{width:100%;height:auto}a{color:#2563eb}</style><h1>Análises completas TCP</h1><p>Quatro campanhas finais, 200 rodadas revalidadas. LAN: cliente ANVS14 e servidor D15-126. Loopback: uma campanha em cada máquina.</p><p>Leia também <a href="PLANO.md">o plano</a> e <a href="RESULTADOS.md">os resultados e limitações</a>.</p>'+cards+'</html>', encoding='utf-8')
    lines = ['# Resultados adicionais', '', 'Base: quatro campanhas finais compatíveis, 50 rodadas cada (N=1 a 10, cinco repetições), total de 200 rodadas revalidadas a partir dos CSVs brutos.', '',
             '| Cenário | Melhor média (Mbps) | N da melhor média | Máximo observado (Mbps) | Ganho N=10 / N=1 |', '|---|---:|---:|---:|---:|']
    for scenario, _ in SOURCES:
        subset = [r for r in stats if r['scenario']==scenario]
        best = max(subset, key=lambda r: r['mean'])
        last = next(r for r in subset if r['n_clients']==10)
        lines.append(f'| {scenario} | {best["mean"]:.3f} | {best["n_clients"]} | {max(r["maximum"] for r in subset):.3f} | {last["speedup_vs_n1"]:.2f}× |')
    lines += ['', '## Como interpretar', '',
              '- Os gráficos conjuntos logarítmicos permitem ver as quatro séries. Os painéis mostram os detalhes em escalas lineares próprias; não compare alturas entre painéis sem ler os eixos. Não há valores ocultos nem eixo interrompido.',
              '- A comparação entre loopbacks usa uma única escala linear para comparar ANVS14 e D15-126 diretamente. Diferenças incluem hardware, sistema, kernel, WSL e condições da coleta; não isolam o efeito de cada componente.',
              '- Ganho relativo é T(N)/T(1), calculado a partir das médias. Eficiência é esse ganho dividido por N (CSV). São razões descritivas; não foram calculados ICs para essas razões.',
              '- O CV entre repetições mede dispersão relativa, enquanto o CV temporal descreve os intervalos da janela útil de cada rodada. Intervalos dentro de uma rodada não são tratados como repetições independentes. O CV temporal não é ponderado pela duração dos intervalos e é sensível aos atrasos da amostragem.',
              '- Jain é calculado por rodada com as vazões individuais na mesma janela: (soma x)² / (N × soma x²). Com N=1 ele vale 1 por definição. Os ICs t são apresentados sem truncamento e podem ultrapassar os limites físicos do índice ou apresentar limites negativos para CV; isso é uma limitação da aproximação, não uma observação negativa.',
              '- As médias têm IC t de 95% (desvio padrão amostral, cinco rodadas, 4 graus de liberdade). São intervalos descritivos sob a hipótese de independência. Ordem crescente de N, poucas repetições e possível autocorrelação limitam inferências; sobreposição de IC não é teste de igualdade.',
              '- Máximo significa o maior valor observado em cinco rodadas, não capacidade teórica. Valores extremos foram preservados.',
              '- Monitoramento de CPU inclui a vida inteira da coleta local, com espera e encerramento; os tempos não estão alinhados ao GO. O CSV usa média ponderada por interval_s e separa CPU total, processos, máquinas e papéis. CPU total é percentual da máquina; em processo, 100% equivale a um processador lógico e pode ser excedido. Não usar como prova causal de gargalo.',
              '- Os registros do ANVS14 cliente em cabo/Wi-Fi complementam o monitoramento; não são outras campanhas de vazão. A carga útil recebida é medida somente pelo servidor. Não há LAN com ANVS14 como servidor nesses dados finais.',
              '- Pilotos de 15 segundos, tentativas falhas e campanhas antigas com amostragem nominal não foram misturados com as finais de 30 segundos e amostragem monotônica.',
              '', '## Rastreabilidade', '', 'Consulte `dados/proveniencia.json`: fontes relativas ao repositório, parâmetros, IDs, arquivos consumidos e SHA-256 combinado (nome relativo + conteúdo, em ordem de caminho). `dados/avisos.txt` registra falhas ou ausências. Os CSVs preservam cenário, N e repetição. Não foi realizada nova coleta de rede.', '']
    (HERE/'RESULTADOS.md').write_text('\n'.join(lines), encoding='utf-8')
    print(f'Concluído: {len(rounds)} rodadas, {len(individuals)} conexões, {len(drawings)} figuras; {len(warnings)} avisos.')


if __name__ == '__main__':
    main()
