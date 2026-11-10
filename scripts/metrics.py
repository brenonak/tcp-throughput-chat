"""Validacao compartilhada, sem dependencias externas."""
import csv
import math
from pathlib import Path

SUMMARY = 'timestamp,label,rep,n_clients,block_bytes,duration_s,bytes_total,bytes_window,window_s,mbps_total,mbps_window'.split(',')
SAMPLES = 'timestamp,label,rep,n_clients,tick_s,client_index,client_name,bytes_cumulative'.split(',')
IDENTITY = ['server_machine_id', 'client_machine_id']
MANIFEST = ['n_clients', 'rep', 'started_at', 'finished_at', 'status', 'reason']


def campaign_identity(config):
    return {key: config.get(key) or 'nao_informado' for key in IDENTITY}


def read_csv(path, header, optional_header=None):
    with Path(path).open(newline='') as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != header and reader.fieldnames != header + (optional_header or []):
            raise ValueError(f'Cabecalho invalido: {path}')
        rows = list(reader)
    if not rows or any(None in r or any(v is None for v in r.values()) for r in rows):
        raise ValueError(f'CSV vazio ou malformado: {path}')
    return rows


def validate_round(directory, config, n, rep):
    directory = Path(directory)
    rows = read_csv(directory / 'results.csv', SUMMARY)
    if len(rows) != 1:
        raise ValueError('Esperada uma linha de resumo')
    row = rows[0]
    for key in SUMMARY[2:]:
        if not math.isfinite(float(row[key])) or float(row[key]) < 0:
            raise ValueError(f'Valor invalido: {key}')
    if (int(row['n_clients']), int(row['rep']), row['label'], int(row['block_bytes'])) != (n, rep, config['label'], 65536):
        raise ValueError('Identificacao da rodada inconsistente')
    if float(row['window_s']) <= 0 or float(row['duration_s']) < config['duration'] - 0.5:
        raise ValueError('Janela vazia ou transmissao terminou antes do previsto')
    samples = read_csv(directory / 'samples.csv', SAMPLES)
    series = {i: {} for i in range(n)}
    for s in samples:
        if (int(s['n_clients']), int(s['rep']), s['label']) != (n, rep, config['label']):
            raise ValueError('Identificacao de amostra inconsistente')
        i, tick, count = (int(s[k]) for k in ('client_index', 'tick_s', 'bytes_cumulative'))
        if i not in series or tick <= 0 or count < 0 or tick in series[i]:
            raise ValueError('Amostra invalida ou duplicada')
        series[i][tick] = count
    ticks = sorted(series[0])
    if not ticks or ticks != list(range(1, ticks[-1] + 1)):
        raise ValueError('Ticks ausentes')
    start, end = config['warmup'], ticks[-1] - config['cooldown']
    if end <= start or float(row['window_s']) != end - start:
        raise ValueError('Janela incompativel com amostras')
    per_client = []
    total_window = 0
    for i, values in series.items():
        if sorted(values) != ticks:
            raise ValueError('Cliente ou tick ausente')
        counts = [values[t] for t in ticks]
        if any(b < a for a, b in zip(counts, counts[1:])):
            raise ValueError('Contador decrescente')
        delta = values[end] - (values[start] if start else 0)
        total_window += delta
        per_client.append({'client_index': i, 'mbps': delta * 8 / ((end - start) * 1e6)})
    if total_window != int(row['bytes_window']) or sum(v[ticks[-1]] for v in series.values()) > int(row['bytes_total']):
        raise ValueError('Contagem de bytes inconsistente')
    computed = total_window * 8 / ((end - start) * 1e6)
    if abs(computed - float(row['mbps_window'])) > 0.00051:
        raise ValueError('Mbps inconsistente com amostras')
    return row, samples, per_client
