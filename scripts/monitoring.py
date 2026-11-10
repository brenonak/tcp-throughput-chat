"""Coleta leve de CPU e interfaces Linux, fora do caminho de transmissao."""
import csv
from datetime import datetime, timezone
import os
from pathlib import Path
import threading
import time


COMMON = ['timestamp', 'elapsed_s', 'interval_s', 'machine_id', 'role', 'n_clients', 'rep']
CPU = COMMON + ['scope', 'name', 'pid', 'cpu_percent']
NETWORK = COMMON + ['interface', 'rx_bytes', 'tx_bytes', 'rx_mbps', 'tx_mbps',
                    'rx_errors', 'tx_errors', 'rx_dropped', 'tx_dropped']


def read_cpu(path=Path('/proc/stat')):
    result = {}
    for line in path.read_text().splitlines():
        fields = line.split()
        if fields and (fields[0] == 'cpu' or fields[0].startswith('cpu') and fields[0][3:].isdigit()):
            # guest e guest_nice ja estao incluidos em user e nice.
            values = list(map(int, fields[1:9]))
            result[fields[0]] = (sum(values), values[3] + values[4])
    return result


def read_process(pid, proc=Path('/proc')):
    # comm pode conter espacos e parenteses. Os indices abaixo comecam no campo state.
    fields = (proc / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()
    return int(fields[11]) + int(fields[12])


def read_network(path=Path('/proc/net/dev')):
    result = {}
    for line in path.read_text().splitlines():
        if ':' in line:
            name, counters = line.rsplit(':', 1)
            values = list(map(int, counters.split()))
            result[name.strip()] = tuple(values[i] for i in (0, 8, 2, 10, 3, 11))
    return result


class RoundMonitor:
    def __init__(self, directory, machine_id, role, n, rep, interface=None):
        self.directory = Path(directory)
        self.identity = dict(machine_id=machine_id, role=role, n_clients=n, rep=rep)
        self.interface = interface
        self.processes = {}
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.warned = set()
        self.previous_cpu = self.previous_net = {}
        self.hz = os.sysconf('SC_CLK_TCK')

    def warn(self, message):
        if message not in self.warned:
            self.warned.add(message)
            with (self.directory / 'monitoring_warnings.txt').open('a') as f:
                f.write(message + '\n')

    def read(self, reader):
        try:
            return reader()
        except (OSError, ValueError, IndexError) as exc:
            self.warn(f'{reader.__name__}: coleta indisponivel: {exc}')
            return {}

    def add_process(self, role, pid):
        with self.lock:
            try:
                self.processes[pid] = (role, read_process(pid), time.monotonic())
            except ProcessLookupError:
                pass
            except FileNotFoundError:
                pass
            except (OSError, ValueError, IndexError) as exc:
                self.warn(f'CPU do processo {role}: {exc}')

    def __enter__(self):
        self.cpu_file = (self.directory / 'cpu.csv').open('w', newline='')
        try:
            self.net_file = (self.directory / 'network.csv').open('w', newline='')
        except BaseException:
            self.cpu_file.close()
            raise
        self.cpu_writer = csv.DictWriter(self.cpu_file, fieldnames=CPU)
        self.net_writer = csv.DictWriter(self.net_file, fieldnames=NETWORK)
        self.cpu_writer.writeheader()
        self.net_writer.writeheader()
        self.started = self.previous_time = time.monotonic()
        self.previous_cpu = self.read(read_cpu)
        self.previous_net = self.read(read_network)
        if self.interface and self.interface not in self.previous_net:
            self.warn(f'Interface {self.interface} ausente; consulte network.csv e --interface')
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        return self

    def sample(self):
        now = time.monotonic()
        interval = now - self.previous_time
        common = dict(self.identity, timestamp=datetime.now(timezone.utc).isoformat(),
                      elapsed_s=now - self.started, interval_s=interval)
        cpus, network = self.read(read_cpu), self.read(read_network)
        for name, (total, idle) in cpus.items():
            if name in self.previous_cpu:
                prev_total, prev_idle = self.previous_cpu[name]
                delta, idle_delta = total - prev_total, idle - prev_idle
                if delta > 0 and 0 <= idle_delta <= delta:
                    self.cpu_writer.writerow(dict(common, scope='system', name=name, pid='',
                                                  cpu_percent=100 * (delta - idle_delta) / delta))
        with self.lock:
            for pid, (role, ticks, previous_time) in list(self.processes.items()):
                try:
                    current = read_process(pid)
                except (FileNotFoundError, ProcessLookupError):
                    del self.processes[pid]
                    continue
                except (OSError, ValueError, IndexError) as exc:
                    self.warn(f'CPU do processo {role}: {exc}')
                    continue
                elapsed = now - previous_time
                if elapsed > 0 and current >= ticks:
                    self.cpu_writer.writerow(dict(common, role=role, interval_s=elapsed, scope='process',
                                                  name=role, pid=pid, cpu_percent=100 * (current - ticks) / self.hz / elapsed))
                self.processes[pid] = (role, current, now)
        for name, counters in network.items():
            if (not self.interface or name == self.interface) and name in self.previous_net:
                delta = [b - a for a, b in zip(self.previous_net[name], counters)]
                if any(value < 0 for value in delta):
                    self.warn(f'Interface {name}: contador reiniciado; intervalo descartado')
                    continue
                rx, tx, rx_errors, tx_errors, rx_dropped, tx_dropped = delta
                self.net_writer.writerow(dict(common, interface=name, rx_bytes=rx, tx_bytes=tx,
                                              rx_mbps=8 * rx / interval / 1e6, tx_mbps=8 * tx / interval / 1e6,
                                              rx_errors=rx_errors, tx_errors=tx_errors,
                                              rx_dropped=rx_dropped, tx_dropped=tx_dropped))
        self.previous_cpu, self.previous_net, self.previous_time = cpus, network, now
        self.cpu_file.flush()
        self.net_file.flush()

    def run(self):
        try:
            while not self.stop.wait(1):
                self.sample()
        except Exception as exc:
            self.warn(f'Monitoramento interrompido: {exc}')

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join()
        try:
            self.sample()
        except Exception as exc:
            self.warn(f'Ultima amostra indisponivel: {exc}')
        finally:
            self.cpu_file.close()
            self.net_file.close()
