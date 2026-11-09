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
from metrics import SUMMARY, SAMPLES, validate_round


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


class RunnerTests(unittest.TestCase):
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
            proc = subprocess.run([sys.executable, str(ROOT / 'scripts/experiments.py'), 'loopback', '--clients', '1', '--repetitions', '1', '--duration', '4', '--warmup', '1', '--cooldown', '1', '--port', str(listener.getsockname()[1]), '--output', str(out)], capture_output=True, timeout=15)
            self.assertNotEqual(proc.returncode, 0)
            with (out / 'manifest.csv').open() as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows[0]['status'], 'failed')
            self.assertFalse((out / 'results.csv').exists())
            self.assertTrue((out / 'rodadas/n01_r001/server.log').exists())

    def test_lan_manual_client_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'server'
            client_out = Path(tmp) / 'client'
            with socket.socket() as reserved:
                reserved.bind(('127.0.0.1', 0))
                port = reserved.getsockname()[1]
            server = subprocess.Popen([sys.executable, str(ROOT / 'scripts/experiments.py'), 'server', '--ip', '127.0.0.2', '--label', 'lan_cabo', '--clients', '1', '--repetitions', '1', '--duration', '4', '--warmup', '1', '--cooldown', '1', '--port', str(port), '--output', str(out)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                deadline = time.monotonic() + 10
                log = out / 'rodadas/n01_r001/server.log'
                while not log.exists() or 'escutando' not in log.read_text():
                    if time.monotonic() > deadline or server.poll() is not None:
                        self.fail('Executor servidor nao iniciou')
                    time.sleep(.05)
                client = subprocess.run([sys.executable, str(ROOT / 'scripts/experiments.py'), 'client', '--ip', '127.0.0.2', '--clients', '1', '--duration', '4', '--port', str(port), '--output', str(client_out)], capture_output=True, timeout=15)
                self.assertEqual(client.returncode, 0, client.stderr.decode())
                self.assertEqual(server.wait(timeout=10), 0)
                self.assertTrue((out / 'results.csv').exists())
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
            proc = subprocess.Popen([sys.executable, str(ROOT / 'scripts/experiments.py'), 'server', '--ip', '127.0.0.2', '--label', 'lan_cabo', '--clients', '1', '--repetitions', '1', '--duration', '4', '--warmup', '1', '--cooldown', '1', '--port', str(port), '--output', str(out)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
