import csv
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from monitoring import RoundMonitor, read_cpu, read_network, read_process


class MonitoringTests(unittest.TestCase):
    def test_linux_counter_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'stat').write_text('cpu 100 20 30 400 5 6 7 8 10 2\ncpu0 100 20 30 400 5 6 7 8 10 2\nintr 1\n')
            self.assertEqual(read_cpu(root / 'stat'), {'cpu': (576, 405), 'cpu0': (576, 405)})
            (root / 'dev').write_text('header\n lo: 125000 1 2 3 0 0 0 0 250000 1 4 5 0 0 0 0\n')
            self.assertEqual(read_network(root / 'dev'), {'lo': (125000, 250000, 2, 4, 3, 5)})
            (root / '123').mkdir()
            (root / '123/stat').write_text('123 (a name ) with spaces) S ' + '0 ' * 10 + '150 50 0 0\n')
            self.assertEqual(read_process(123, root), 200)

    def test_percentages_and_network_rates_use_measured_interval(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch('monitoring.threading.Thread'), \
                patch('monitoring.time.monotonic', return_value=10.) as clock, \
                patch('monitoring.read_cpu', return_value={'cpu': (1000, 700), 'cpu0': (500, 350)}) as cpu, \
                patch('monitoring.read_network', return_value={'lo': (0, 0, 0, 0, 0, 0)}) as net, \
                patch('monitoring.read_process', return_value=100) as process:
            with RoundMonitor(tmp, 'pc_a', 'loopback', 2, 1, 'lo') as monitor:
                monitor.hz = 100
                monitor.add_process('server', 123)
                clock.return_value = 12.
                cpu.return_value = {'cpu': (1200, 800), 'cpu0': (600, 375)}
                net.return_value = {'lo': (250000, 500000, 1, 2, 3, 4), 'eth0': (0, 0, 0, 0, 0, 0)}
                process.return_value = 400
                monitor.sample()
                clock.return_value = 13.
            with (Path(tmp) / 'cpu.csv').open() as f:
                rows = list(csv.DictReader(f))
            first = {row['name']: row for row in rows[:3]}
            self.assertEqual(float(first['cpu']['cpu_percent']), 50.)
            self.assertEqual(float(first['cpu0']['cpu_percent']), 75.)
            self.assertEqual(float(first['server']['cpu_percent']), 150.)
            self.assertEqual(first['server']['machine_id'], 'pc_a')
            with (Path(tmp) / 'network.csv').open() as f:
                rows = list(csv.DictReader(f))
            self.assertEqual({row['interface'] for row in rows}, {'lo'})
            self.assertEqual(float(rows[0]['rx_mbps']), 1.)
            self.assertEqual(float(rows[0]['tx_mbps']), 2.)
            self.assertEqual([int(rows[0][key]) for key in ('rx_errors', 'tx_errors', 'rx_dropped', 'tx_dropped')], [1, 2, 3, 4])

    def test_missing_interface_and_exited_process(self):
        with tempfile.TemporaryDirectory() as tmp, patch('monitoring.threading.Thread'):
            with RoundMonitor(tmp, 'pc_a', 'server', 1, 1, 'nonexistent_interface') as monitor:
                with patch('monitoring.read_process', side_effect=FileNotFoundError):
                    monitor.add_process('client', 123)
                self.assertEqual(monitor.processes, {})
            self.assertIn('Interface nonexistent_interface ausente', (Path(tmp) / 'monitoring_warnings.txt').read_text())


if __name__ == '__main__':
    unittest.main()
