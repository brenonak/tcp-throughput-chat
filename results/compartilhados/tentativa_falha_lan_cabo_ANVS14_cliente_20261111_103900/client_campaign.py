import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

root = Path.cwd()
out = Path(sys.argv[1]).resolve()
manifest = out / 'manifest.csv'
identity = dict(machine_id='ANVS14', server_machine_id='D15-126')
config = dict(mode='client_campaign', ip='192.168.50.1', port=5000,
              label='lan_cabo', clients=list(range(1, 11)), repetitions=5,
              duration=30, warmup=5, cooldown=5, interval=5,
              interface='eth0', monitoring=True, **identity)
(out / 'campaign_config.json').write_text(json.dumps(config, indent=2) + '\n')
fields = ['n_clients', 'rep', 'started_at', 'finished_at', 'status', 'returncode', 'directory']
with manifest.open('x', newline='') as stream:
    csv.DictWriter(stream, fieldnames=fields).writeheader()
for n in range(1, 11):
    for rep in range(1, 6):
        directory = out / f'n{n:02}_r{rep:03}'
        command = ['bash', 'scripts/run_experiments.sh', 'client',
                   '--machine-id', 'ANVS14', '--server-machine-id', 'D15-126',
                   '--ip', '192.168.50.1', '--port', '5000', '--label', 'lan_cabo',
                   '--interface', 'eth0', '--clients', str(n), '--rep', str(rep),
                   '--duration', '30', '--warmup', '5', '--cooldown', '5',
                   '--output', str(directory)]
        started = datetime.now(timezone.utc).isoformat()
        print(f'CLIENTE: iniciando N={n}, repeticao={rep}', flush=True)
        with (out / f'n{n:02}_r{rep:03}_executor.log').open('w') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        row = dict(n_clients=n, rep=rep, started_at=started,
                   finished_at=datetime.now(timezone.utc).isoformat(),
                   status='completed' if result.returncode == 0 else 'failed',
                   returncode=result.returncode, directory=directory.name)
        with manifest.open('a', newline='') as stream:
            csv.DictWriter(stream, fieldnames=fields).writerow(row)
        print(f'CLIENTE: N={n}, repeticao={rep}, status={row["status"]}, codigo={result.returncode}', flush=True)
        if result.returncode != 0:
            print((out / f'n{n:02}_r{rep:03}_executor.log').read_text(), flush=True)
            raise SystemExit(result.returncode)
        if n != 10 or rep != 5:
            time.sleep(5)
print('CLIENTE: 50 rodadas concluidas. Validacao de vazao deve ser conferida no servidor.', flush=True)