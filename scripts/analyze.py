#!/usr/bin/env python3
"""Analisa somente rodadas validadas; exporta CSV, PNG e PDF."""
import argparse
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
from scipy.stats import t

from metrics import IDENTITY, MANIFEST, campaign_identity, read_csv, validate_round


def describe(values):
    count = len(values)
    mean = values.mean()
    std = values.std(ddof=1) if count > 1 else float('nan')
    half = t.ppf(0.975, count - 1) * std / count ** 0.5 if count > 1 else float('nan')
    return dict(count=count, maximum=values.max(), mean=mean, std=std,
                ci95_low=mean - half, ci95_high=mean + half)


def campaign_legend(campaign, label, identity):
    server, client = (identity[key] for key in IDENTITY)
    machines = server if label == 'loopback' and server == client else f'{client} -> {server}'
    return f'{label}: {machines} ({Path(campaign).name})'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('campaigns', nargs='+', type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    records, connections, warnings = [], [], []
    baseline = None
    seen = set()
    for campaign in args.campaigns:
        campaign = campaign.resolve()
        if campaign in seen:
            p.error('Campanha duplicada')
        seen.add(campaign)
        config = json.loads((campaign / 'config.json').read_text())
        identity = campaign_identity(config)
        if 'nao_informado' in identity.values():
            warnings.append(f'{campaign.name}: campanha antiga sem identificacao completa das maquinas')
        signature = tuple(config[k] for k in ('duration', 'warmup', 'cooldown', 'block_bytes')) + (config.get('sample_timing', 'nominal'),)
        if baseline is not None and signature != baseline:
            p.error('Campanhas possuem parametros incompativeis')
        baseline = signature
        manifest = read_csv(campaign / 'manifest.csv', MANIFEST, optional_header=IDENTITY)
        valid = set()
        for attempt in manifest:
            if any(key in attempt for key in IDENTITY) and campaign_identity(attempt) != identity:
                raise ValueError('Maquinas do manifesto inconsistentes com config.json')
            n, rep = int(attempt['n_clients']), int(attempt['rep'])
            if attempt['status'] != 'valid':
                warnings.append(f'{campaign.name}: N={n}, rep={rep} falhou: {attempt["reason"]}')
                continue
            if (n, rep) in valid:
                raise ValueError('Rodada duplicada no manifesto')
            row, _, individual = validate_round(campaign / 'rodadas' / f'n{n:02}_r{rep:03}', config, n, rep)
            valid.add((n, rep))
            records.append(dict(campaign=str(campaign), label=config['label'], n_clients=n, rep=rep,
                                mbps=float(row['mbps_window']), window_s=float(row['window_s']), **identity))
            for value in individual:
                connections.append(dict(campaign=str(campaign), label=config['label'], n_clients=n, rep=rep, **identity, **value))
        for n in range(1, 11):
            count = sum(pair[0] == n for pair in valid)
            if count != config['repetitions']:
                warnings.append(f'{campaign.name}: N={n}: {count}/{config["repetitions"]} repeticoes validas')
    if not records:
        raise ValueError('Nenhuma rodada valida para analisar')
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        p.error('Diretorio de analise deve estar vazio ou nao existir')
    output.mkdir(parents=True, exist_ok=True)
    data = pd.DataFrame(records)
    individual = pd.DataFrame(connections)
    statistics = []
    for (campaign, label, n), group in data.groupby(['campaign', 'label', 'n_clients']):
        identity = campaign_identity(group.iloc[0])
        statistics.append(dict(campaign=campaign, label=label, n_clients=n, **identity, **describe(group.mbps)))
    summary = pd.DataFrame(statistics)
    summary.to_csv(output / 'summary.csv', index=False)
    data.to_csv(output / 'rounds.csv', index=False)
    individual.to_csv(output / 'per_client.csv', index=False)
    for metric, filename in [('maximum', 'throughput_max'), ('mean', 'throughput_mean')]:
        fig, ax = plt.subplots(figsize=(8, 5))
        for (campaign, label), group in summary.groupby(['campaign', 'label']):
            group = group.sort_values('n_clients')
            legend = campaign_legend(campaign, label, campaign_identity(group.iloc[0]))
            ax.plot(group.n_clients, group[metric], marker='o', label=legend)
            if metric == 'mean':
                error = group[group['count'] > 1]
                ax.errorbar(error.n_clients, error['mean'], yerr=error.ci95_high - error['mean'], fmt='none', capsize=4)
        ax.set(xlabel='Clientes simultaneos', ylabel='Vazao agregada (Mbps)', xticks=range(1, 11))
        ax.grid(alpha=.3)
        ax.legend(fontsize='small')
        fig.tight_layout()
        for extension in ('png', 'pdf'):
            fig.savefig(output / f'{filename}.{extension}')
        plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 5))
    for (campaign, label), group in individual.groupby(['campaign', 'label']):
        ax.scatter(group.n_clients, group.mbps, alpha=.35, s=15,
                   label=campaign_legend(campaign, label, campaign_identity(group.iloc[0])))
    ax.set(xlabel='Clientes simultaneos', ylabel='Vazao por conexao (Mbps)', xticks=range(1, 11))
    ax.grid(alpha=.3)
    ax.legend(fontsize='small')
    fig.tight_layout()
    for extension in ('png', 'pdf'):
        fig.savefig(output / f'per_client.{extension}')
    plt.close(fig)
    (output / 'warnings.txt').write_text('\n'.join(warnings) + '\n')
    for warning in warnings:
        print(f'Aviso: {warning}', file=sys.stderr)
    print(f'Analise salva em {output}')


if __name__ == '__main__':
    main()
