"""Executor local e coordenador manual LAN. Requer Linux e Python 3."""
import argparse
from contextlib import ExitStack, nullcontext
import csv
import json
import os
from pathlib import Path
import platform
import re
import shlex
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone

from metrics import SUMMARY, SAMPLES, IDENTITY, MANIFEST, validate_round
from monitoring import RoundMonitor

ROOT = Path(__file__).resolve().parents[1]
children = []


def stamp():
    return datetime.now(timezone.utc).isoformat()


def stop_children():
    for proc in children:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
    for proc in children:
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
    children.clear()


def launch(command, log):
    with log.open('w') as out:
        proc = subprocess.Popen(command, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    children.append(proc)
    return proc


def wait_marker(proc, log, marker, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f'Servidor terminou antes de {marker}. Consulte {log}')
        if marker in log.read_text(errors='replace'):
            return
        time.sleep(0.05)
    raise TimeoutError(f'Tempo esgotado esperando {marker}')


def append_csv(path, header, rows):
    exists = path.exists()
    with path.open('a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def machine_id(value):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', value):
        raise argparse.ArgumentTypeError('ID de maquina deve ter 1 a 64 letras ASCII, numeros, pontos, hifens ou sublinhados, iniciando com letra ou numero')
    return value


def identify_machines(mode, local_id, server_id=None, client_id=None):
    if mode == 'loopback':
        if server_id is not None or client_id is not None:
            raise ValueError('Loopback usa apenas --machine-id para ambos os papeis')
        return dict(server_machine_id=local_id, client_machine_id=local_id)
    if mode == 'server':
        if server_id is not None or client_id is None:
            raise ValueError('Modo server exige --client-machine-id; identifique o servidor com --machine-id')
        server_id = local_id
    else:
        if client_id is not None or server_id is None:
            raise ValueError('Modo client exige --server-machine-id; identifique o cliente com --machine-id')
        client_id = local_id
    if server_id == client_id:
        raise ValueError('Na LAN, servidor e cliente devem ter IDs de maquina distintos')
    return dict(server_machine_id=server_id, client_machine_id=client_id)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['loopback', 'server', 'client'])
    p.add_argument('--ip', default='127.0.0.1')
    p.add_argument('--label', choices=['loopback', 'lan_cabo', 'lan_wifi'])
    p.add_argument('--port', type=int, default=5000)
    p.add_argument('--duration', type=int, default=30)
    p.add_argument('--repetitions', type=int, default=10)
    p.add_argument('--clients', default='1,2,3,4,5,6,7,8,9,10')
    p.add_argument('--warmup', type=int, default=5)
    p.add_argument('--cooldown', type=int, default=5)
    p.add_argument('--interval', type=float, default=5)
    p.add_argument('--rep', type=int, default=1, help='Identificacao no modo client')
    p.add_argument('--output', type=Path, help='Diretorio novo, nunca sobrescrito')
    p.add_argument('--interface')
    p.add_argument('--no-monitor', action='store_true', help='Desativa a coleta de CPU e rede por segundo')
    p.add_argument('--machine-id', type=machine_id, default=socket.gethostname(),
                   help='ID estavel desta maquina (padrao: hostname). Use o mesmo em todas as campanhas')
    p.add_argument('--client-machine-id', type=machine_id, help='ID da outra maquina no modo server')
    p.add_argument('--server-machine-id', type=machine_id, help='ID da outra maquina no modo client')
    args = p.parse_args()
    try:
        identity = identify_machines(args.mode, args.machine_id, args.server_machine_id, args.client_machine_id)
    except ValueError as exc:
        p.error(str(exc))
    try:
        ns = [int(v) for v in args.clients.split(',')]
    except ValueError:
        p.error('--clients deve ser uma lista como 1,5,10')
    if not ns or len(set(ns)) != len(ns) or any(n < 1 or n > 10 for n in ns):
        p.error('Clientes devem ser distintos, entre 1 e 10')
    if not 1 <= args.port <= 65535 or not 1 <= args.duration <= 3600 or args.repetitions < 1 or args.rep < 1:
        p.error('Porta, duracao ou repeticoes invalidas')
    if args.warmup < 0 or args.cooldown < 0 or not 0 <= args.interval < float('inf'):
        p.error('Descartes e intervalo devem ser nao negativos')
    if args.mode != 'client' and args.duration <= args.warmup + args.cooldown + 1:
        p.error('Duracao deve superar warmup + cooldown + 1')
    if args.mode == 'client' and len(ns) != 1:
        p.error('Modo client exige um unico N em --clients')
    if args.mode == 'server' and (args.ip == '127.0.0.1' or args.label not in ('lan_cabo', 'lan_wifi')):
        p.error('Modo server exige --ip acessivel na rede e --label lan_cabo ou lan_wifi')
    if args.mode == 'loopback' and args.label not in (None, 'loopback'):
        p.error('Modo loopback exige label loopback')
    label = args.label or ('loopback' if args.mode == 'loopback' else 'lan_cabo')
    out = args.output or ROOT / 'results' / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '_' + label + '_' + args.mode)
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    print(f'Saida: {out}', flush=True)
    print(f'Maquinas: servidor={identity["server_machine_id"]}, cliente={identity["client_machine_id"]}', flush=True)
    config = vars(args).copy()
    config.update(output=str(out), clients=sorted(ns), label=label, block_bytes=65536,
                  **identity,
                  machine={'id': args.machine_id, 'hostname': socket.gethostname(),
                           'system': platform.system(), 'release': platform.release(),
                           'architecture': platform.machine()},
                  compile_flags='-O2 -Wall -Wextra -pthread', created_at=stamp(),
                  monitoring={'enabled': not args.no_monitor, 'interval_s': 1,
                              'interface': args.interface or ('lo' if args.mode == 'loopback' else 'all')},
                  order=[{'n_clients': n, 'rep': r} for n in sorted(ns)
                         for r in range(1, args.repetitions + 1)])
    (out / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
    subprocess.run(['make', '-C', str(ROOT), 'client' if args.mode == 'client' else 'all'], check=True)
    subprocess.run(['bash', str(ROOT / 'scripts/coleta_ambiente.sh'), str(out / 'ambiente' / args.mode), args.interface or ''], check=True)
    if args.mode == 'client':
        with nullcontext() if args.no_monitor else RoundMonitor(out, args.machine_id, 'client', ns[0], args.rep, args.interface) as monitor:
            proc = launch([str(ROOT / 'build/chat_client'), args.ip, str(args.port), str(args.duration), str(ns[0])], out / f'client_n{ns[0]}_r{args.rep}.log')
            if monitor:
                monitor.add_process('client', proc.pid)
            rc = proc.wait(timeout=60 + args.duration + 30)
        if rc:
            raise RuntimeError(f'Cliente terminou com codigo {rc}')
        return
    manifest_header = MANIFEST + IDENTITY
    for n in sorted(ns):
        for rep in range(1, args.repetitions + 1):
            directory = out / 'rodadas' / f'n{n:02}_r{rep:03}'
            directory.mkdir(parents=True)
            entry = dict(n_clients=n, rep=rep, started_at=stamp(), status='failed', reason='', **identity)
            monitoring = ExitStack()
            try:
                monitor = monitoring.enter_context(nullcontext() if args.no_monitor else
                    RoundMonitor(directory, args.machine_id, args.mode, n, rep,
                                 args.interface or ('lo' if args.mode == 'loopback' else None)))
                command = [str(ROOT / 'build/chat_server'), '-p', str(args.port), '-n', str(n), '-d', str(args.duration), '-w', str(args.warmup), '-c', str(args.cooldown), '-r', str(rep), '-l', label, '-o', str(directory / 'results.csv'), '-s', str(directory / 'samples.csv')]
                (directory / 'commands.json').write_text(json.dumps({'server': command}, indent=2))
                log = directory / 'server.log'
                server = launch(command, log)
                if monitor:
                    monitor.add_process('server', server.pid)
                wait_marker(server, log, '[server] escutando', 10)
                print(f'Rodada N={n}, repeticao={rep}', flush=True)
                client_command = [str(ROOT / 'build/chat_client'), '127.0.0.1', str(args.port), str(args.duration), str(n)]
                client = None
                if args.mode == 'loopback':
                    (directory / 'commands.json').write_text(json.dumps({'server': command, 'client': client_command}, indent=2))
                    client = launch(client_command, directory / 'client.log')
                    if monitor:
                        monitor.add_process('client', client.pid)
                else:
                    manual = ['bash', 'scripts/run_experiments.sh', 'client', '--ip', args.ip, '--port', str(args.port), '--duration', str(args.duration), '--clients', str(n), '--rep', str(rep), '--label', label,
                              '--machine-id', identity['client_machine_id'], '--server-machine-id', identity['server_machine_id']]
                    if args.no_monitor:
                        manual.append('--no-monitor')
                    (directory / 'commands.json').write_text(json.dumps({'server': command, 'client': manual}, indent=2))
                    print('No computador cliente, na raiz do repositorio:\n' + shlex.join(manual), flush=True)
                wait_marker(server, log, '[server] START', 60)
                rc = server.wait(timeout=args.duration + 30)
                if rc or (client is not None and client.wait(timeout=5)):
                    raise RuntimeError('Servidor ou cliente terminou com erro')
                row, samples, _ = validate_round(directory, config, n, rep)
                append_csv(out / 'results.csv', SUMMARY + IDENTITY, [dict(row, **identity)])
                append_csv(out / 'samples.csv', SAMPLES + IDENTITY, [dict(sample, **identity) for sample in samples])
                entry['status'] = 'valid'
            except BaseException as exc:
                entry['reason'] = str(exc) or type(exc).__name__
                raise
            finally:
                monitoring.close()
                stop_children()
                entry['finished_at'] = stamp()
                append_csv(out / 'manifest.csv', manifest_header, [entry])
            if n != max(ns) or rep != args.repetitions:
                time.sleep(args.interval)
    print('Campanha concluida.', flush=True)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: sys.exit('Execucao interrompida'))
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        print(f'Falha: {exc}', file=sys.stderr)
        sys.exit(1)
    finally:
        stop_children()
