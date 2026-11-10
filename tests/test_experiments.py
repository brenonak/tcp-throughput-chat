import csv
import json
from pathlib import Path
import socket
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from metrics import SUMMARY, SAMPLES, IDENTITY, MANIFEST, validate_round


class MetricsTests(unittest.TestCase):
    def test_known_window_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            config = dict(label='loopback', duration=4, warmup=1, cooldown=1)
            with (directory / 'results.csv').open('w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(SUMMARY)
                writer.writerow(['now', 'loopback', 1, 1, 65536, 4, 5000000, 2000000, 2, 10, 8])
            with (directory / 'samples.csv').open('w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(SAMPLES)
                for tick in range(1, 5):
                    writer.writerow(['now', 'loopback', 1, 1, tick, 0, 'cliente', tick * 1000000])
            _, _, individual = validate_round(directory, config, 1, 1)
            self.assertEqual(individual[0]['mbps'], 8)
            path = directory / 'samples.csv'
            path.write_text(path.read_text().replace('4000000', '1'))
            with self.assertRaisesRegex(ValueError, 'decrescente'):
                validate_round(directory, config, 1, 1)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen()
        self.listener.settimeout(3)
        self.addCleanup(self.listener.close)

    def start_client(self):
        proc = subprocess.Popen([str(ROOT / 'build/chat_client'), '127.0.0.1', str(self.listener.getsockname()[1]), '1', '1'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        conn, _ = self.listener.accept()
        self.addCleanup(conn.close)
        conn.settimeout(3)
        name = b''
        while not name.endswith(b'\n'):
            name += conn.recv(1)
        return proc, conn

    def test_wait_and_fragmented_go(self):
        proc, conn = self.start_client()
        conn.settimeout(.2)
        with self.assertRaises(socket.timeout):
            conn.recv(1)
        conn.sendall(b'G')
        with self.assertRaises(socket.timeout):
            conn.recv(1)
        start = time.monotonic()
        conn.sendall(b'O\n')
        conn.settimeout(3)
        count = 0
        while True:
            data = conn.recv(65536)
            if not data:
                break
            count += len(data)
        self.assertGreater(count, 0)
        self.assertGreaterEqual(time.monotonic() - start, .95)
        self.assertEqual(proc.wait(timeout=3), 0)

    def test_invalid_go(self):
        proc, conn = self.start_client()
        conn.sendall(b'NO\n')
        self.assertNotEqual(proc.wait(timeout=3), 0)

    def test_disconnect_before_go(self):
        proc, conn = self.start_client()
        conn.close()
        self.assertNotEqual(proc.wait(timeout=3), 0)

    def start_server(self, n):
        port = self.listener.getsockname()[1]
        self.listener.close()
        proc = subprocess.Popen([str(ROOT / 'build/chat_server'), '-p', str(port), '-n', str(n), '-d', '4', '-w', '1', '-c', '1'], cwd=self.tmp.name, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        self.addCleanup(proc.stderr.close)
        while b'escutando' not in proc.stderr.readline():
            if proc.poll() is not None:
                self.fail('Servidor nao iniciou')
        return proc, port

    def test_server_waits_for_all_names(self):
        proc, port = self.start_server(2)
        with socket.create_connection(('127.0.0.1', port)) as a, socket.create_connection(('127.0.0.1', port)) as b:
            a.sendall(b'primeiro\n')
            b.sendall(b'seg')
            a.settimeout(.2)
            with self.assertRaises(socket.timeout):
                a.recv(3)
            b.sendall(b'undo\n')
            a.settimeout(3)
            b.settimeout(3)
            self.assertEqual(a.recv(3, socket.MSG_WAITALL), b'GO\n')
            self.assertEqual(b.recv(3, socket.MSG_WAITALL), b'GO\n')
        self.assertEqual(proc.wait(timeout=3), 0)

    def test_server_rejects_incomplete_name(self):
        proc, port = self.start_server(2)
        with socket.create_connection(('127.0.0.1', port)) as conn:
            conn.sendall(b'incompleto')
        self.assertNotEqual(proc.wait(timeout=3), 0)


class AnalysisTests(unittest.TestCase):
    def test_statistics(self):
        import pandas as pd
        from analyze import describe
        result = describe(pd.Series([10., 20., 30.]))
        self.assertEqual(result['mean'], 20)
        self.assertEqual(result['std'], 10)
        self.assertAlmostEqual(result['ci95_high'], 44.841377, places=5)
        self.assertTrue(pd.isna(describe(pd.Series([10.]))['std']))

    def test_machine_roles_in_analysis_and_legacy_campaign(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaigns = []
            roles = [('loopback', 'pc_a', 'pc_a'), ('loopback', 'pc_b', 'pc_b'),
                     ('lan_cabo', 'pc_a', 'pc_b'), ('lan_cabo', 'pc_b', 'pc_a'),
                     ('loopback', None, None)]
            for index, (label, server, client) in enumerate(roles):
                campaign = root / f'campaign_{index}'
                directory = campaign / 'rodadas/n01_r001'
                directory.mkdir(parents=True)
                config = dict(label=label, duration=4, warmup=1, cooldown=1, block_bytes=65536, repetitions=1)
                identity = dict(server_machine_id=server, client_machine_id=client) if server else {}
                config.update(identity)
                (campaign / 'config.json').write_text(json.dumps(config))
                with (campaign / 'manifest.csv').open('w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=MANIFEST + (IDENTITY if server else []))
                    writer.writeheader()
                    writer.writerow(dict(n_clients=1, rep=1, started_at='now', finished_at='now',
                                         status='valid', reason='', **identity))
                with (directory / 'results.csv').open('w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(SUMMARY)
                    writer.writerow(['now', label, 1, 1, 65536, 4, 5000000, 2000000, 2, 10, 8])
                with (directory / 'samples.csv').open('w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(SAMPLES)
                    for tick in range(1, 5):
                        writer.writerow(['now', label, 1, 1, tick, 0, 'cliente', tick * 1000000])
                campaigns.append(campaign)
            output = root / 'analysis'
            command = [sys.executable, str(ROOT / 'scripts/analyze.py'), *map(str, campaigns), '--output', str(output)]
            proc = subprocess.run(command, capture_output=True, text=True, timeout=45)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            for filename in ('summary.csv', 'rounds.csv', 'per_client.csv'):
                with (output / filename).open() as f:
                    rows = list(csv.DictReader(f))
                actual = {(r['label'], r['server_machine_id'], r['client_machine_id']) for r in rows}
                expected = {(label, server or 'nao_informado', client or 'nao_informado')
                            for label, server, client in roles}
                self.assertEqual(actual, expected)
                self.assertEqual(len(rows), 5)
            self.assertIn('sem identificacao', (output / 'warnings.txt').read_text())
            for name in ('throughput_max', 'throughput_mean', 'per_client'):
                for ext in ('png', 'pdf'):
                    self.assertGreater((output / f'{name}.{ext}').stat().st_size, 0)
            manifest = campaigns[2] / 'manifest.csv'
            manifest.write_text(manifest.read_text().replace('pc_a', 'pc_errado'))
            proc = subprocess.run(command, capture_output=True, text=True, timeout=45)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn('Maquinas do manifesto inconsistentes', proc.stderr)


class RunnerTests(unittest.TestCase):
    def test_machine_identity_validation(self):
        from experiments import identify_machines, machine_id
        import argparse
        self.assertEqual(identify_machines('loopback', 'pc_a'),
                         dict(server_machine_id='pc_a', client_machine_id='pc_a'))
        self.assertEqual(identify_machines('server', 'pc_a', client_id='pc_b'),
                         identify_machines('client', 'pc_b', server_id='pc_a'))
        for mode, local, server, client in [('server', 'a', None, None), ('client', 'b', None, None),
                                           ('server', 'a', None, 'a'), ('client', 'a', 'a', None),
                                           ('loopback', 'a', None, 'b')]:
            with self.subTest(mode=mode, local=local, server=server, client=client):
                with self.assertRaises(ValueError):
                    identify_machines(mode, local, server, client)
        for value in ('', 'pc a', '../pc', 'a' * 65):
            with self.assertRaises(argparse.ArgumentTypeError):
                machine_id(value)

    def test_loopback_records_both_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'loopback'
            with socket.socket() as reserved:
                reserved.bind(('127.0.0.1', 0))
                port = reserved.getsockname()[1]
            proc = subprocess.run([sys.executable, str(ROOT / 'scripts/experiments.py'), 'loopback',
                                   '--machine-id', 'pc_a', '--clients', '1', '--repetitions', '1',
                                   '--duration', '4', '--warmup', '1', '--cooldown', '1',
                                   '--port', str(port), '--output', str(out)], capture_output=True, text=True, timeout=20)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            config = json.loads((out / 'config.json').read_text())
            self.assertEqual(config['machine']['id'], 'pc_a')
            self.assertEqual(config['machine']['hostname'], socket.gethostname())
            self.assertEqual(config['server_machine_id'], 'pc_a')
            self.assertEqual(config['client_machine_id'], 'pc_a')
            for filename in ('results.csv', 'samples.csv', 'manifest.csv'):
                with (out / filename).open() as f:
                    rows = list(csv.DictReader(f))
                self.assertTrue(rows)
                self.assertTrue(all(r['server_machine_id'] == r['client_machine_id'] == 'pc_a' for r in rows))
            validate_round(out / 'rodadas/n01_r001', config, 1, 1)
            directory = out / 'rodadas/n01_r001'
            with (directory / 'cpu.csv').open() as f:
                cpu = list(csv.DictReader(f))
            self.assertTrue({'server', 'client'} <= {r['role'] for r in cpu if r['scope'] == 'process'})
            self.assertTrue(any(r['name'] == 'cpu0' for r in cpu))
            with (directory / 'network.csv').open() as f:
                network = list(csv.DictReader(f))
            self.assertTrue(network)
            self.assertEqual({r['interface'] for r in network}, {'lo'})
            self.assertTrue(any(int(r['rx_bytes']) > 0 for r in network))
            self.assertTrue(all(r['machine_id'] == 'pc_a' for r in cpu + network))

    def test_wait_marker_timeout(self):
        from experiments import wait_marker
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'server.log'
            log.write_text('esperando clientes')
            proc = Mock()
            proc.poll.return_value = None
            with self.assertRaises(TimeoutError):
                wait_marker(proc, log, 'START', .05)

    def test_busy_port_is_failed_and_preserved(self):
        with socket.socket() as listener, tempfile.TemporaryDirectory() as tmp:
            listener.bind(('0.0.0.0', 0))
            listener.listen()
            out = Path(tmp) / 'campaign'
            proc = subprocess.run([sys.executable, str(ROOT / 'scripts/experiments.py'), 'loopback', '--no-monitor', '--clients', '1', '--repetitions', '1', '--duration', '4', '--warmup', '1', '--cooldown', '1', '--port', str(listener.getsockname()[1]), '--output', str(out)], capture_output=True, timeout=15)
            self.assertNotEqual(proc.returncode, 0)
            with (out / 'manifest.csv').open() as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]['status'], 'failed')
            self.assertFalse((out / 'results.csv').exists())
            self.assertTrue((out / 'rodadas/n01_r001/server.log').exists())
            self.assertFalse((out / 'rodadas/n01_r001/cpu.csv').exists())

    def test_lan_manual_client_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'server'
            client_out = Path(tmp) / 'client'
            with socket.socket() as reserved:
                reserved.bind(('127.0.0.1', 0))
                port = reserved.getsockname()[1]
            server = subprocess.Popen([sys.executable, str(ROOT / 'scripts/experiments.py'), 'server', '--machine-id', 'pc_a', '--client-machine-id', 'pc_b', '--ip', '127.0.0.2', '--label', 'lan_cabo', '--clients', '1', '--repetitions', '1', '--duration', '4', '--warmup', '1', '--cooldown', '1', '--port', str(port), '--output', str(out)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                deadline = time.monotonic() + 10
                log = out / 'rodadas/n01_r001/server.log'
                commands_path = out / 'rodadas/n01_r001/commands.json'
                commands = {}
                while 'client' not in commands or not log.exists() or 'escutando' not in log.read_text():
                    if time.monotonic() > deadline or server.poll() is not None:
                        self.fail('Executor servidor nao iniciou')
                    time.sleep(.05)
                    try:
                        commands = json.loads(commands_path.read_text())
                    except (FileNotFoundError, json.JSONDecodeError):
                        commands = {}
                client = subprocess.run(['bash', *commands['client'][1:], '--output', str(client_out)], capture_output=True, timeout=15)
                self.assertEqual(client.returncode, 0, client.stderr.decode())
                self.assertEqual(server.wait(timeout=10), 0)
                self.assertTrue((out / 'results.csv').exists())
                for campaign in (out, client_out):
                    config = json.loads((campaign / 'config.json').read_text())
                    self.assertEqual(config['server_machine_id'], 'pc_a')
                    self.assertEqual(config['client_machine_id'], 'pc_b')
                self.assertEqual(json.loads((client_out / 'config.json').read_text())['machine']['id'], 'pc_b')
                for directory, machine, role in ((out / 'rodadas/n01_r001', 'pc_a', 'server'),
                                                 (client_out, 'pc_b', 'client')):
                    with (directory / 'cpu.csv').open() as f:
                        cpu = list(csv.DictReader(f))
                    self.assertTrue(any(r['scope'] == 'process' and r['role'] == role for r in cpu))
                    self.assertTrue(all(r['machine_id'] == machine for r in cpu))
                    with (directory / 'network.csv').open() as f:
                        self.assertTrue(list(csv.DictReader(f)))
            finally:
                if server.poll() is None:
                    server.terminate()
                    server.wait(timeout=5)
                server.stdout.close()

    def test_interrupt_cleans_server(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'server'
            with socket.socket() as reserved:
                reserved.bind(('127.0.0.1', 0))
                port = reserved.getsockname()[1]
            proc = subprocess.Popen([sys.executable, str(ROOT / 'scripts/experiments.py'), 'server', '--machine-id', 'pc_a', '--client-machine-id', 'pc_b', '--ip', '127.0.0.2', '--label', 'lan_cabo', '--clients', '1', '--repetitions', '1', '--duration', '4', '--warmup', '1', '--cooldown', '1', '--port', str(port), '--output', str(out)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                log = out / 'rodadas/n01_r001/server.log'
                deadline = time.monotonic() + 10
                while not log.exists() or 'escutando' not in log.read_text():
                    if time.monotonic() > deadline or proc.poll() is not None:
                        self.fail('Servidor nao iniciou')
                    time.sleep(.05)
                proc.send_signal(signal.SIGINT)
                self.assertNotEqual(proc.wait(timeout=5), 0)
                with socket.socket() as probe:
                    self.assertNotEqual(probe.connect_ex(('127.0.0.1', port)), 0)
                with (out / 'manifest.csv').open() as f:
                    self.assertEqual(next(csv.DictReader(f))['status'], 'failed')
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
