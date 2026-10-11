#!/usr/bin/env python3
"""Read-only, stdlib system sampler. JSON lines; stdin: open / close."""
import csv
import glob
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time

PROC = Path('/proc')
HZ = os.sysconf('SC_CLK_TCK')
PAGE = os.sysconf('SC_PAGE_SIZE')

def read(path):
    return Path(path).read_text()

def cpu_counters():
    result = {}
    for line in read(PROC / 'stat').splitlines():
        fields = line.split()
        if fields and fields[0].startswith('cpu'):
            values = list(map(int, fields[1:9]))  # guest already included in user/nice
            result[fields[0]] = (sum(values), values[3] + values[4])
    return result

def cpu_percent(old, new):
    total = new[0] - old[0]
    return round(max(0, min(100, 100 * (total - (new[1] - old[1])) / total)), 1) if total > 0 else None

def memory():
    m = {}
    for line in read(PROC / 'meminfo').splitlines():
        key, value = line.split(':', 1)
        m[key] = int(value.split()[0]) * 1024
    total = m['MemTotal']
    used = total - m['MemAvailable']
    return dict(total=total, used=used, available=m['MemAvailable'], percent=round(used / total * 100, 1), swap_total=m['SwapTotal'], swap_used=m['SwapTotal']-m['SwapFree'])

def number(value):
    try:
        return float(value)
    except ValueError:
        return None

def nvidia_gpu():
    if not os.access('/usr/bin/nvidia-smi', os.X_OK):
        return dict(available=False, error='GPU telemetry unavailable')
    try:
        p = subprocess.run(['/usr/bin/nvidia-smi', '--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,fan.speed', '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=1.5)
        if p.returncode:
            raise ValueError('NVIDIA telemetry unavailable')
        cards = []
        for row in csv.reader(p.stdout.splitlines(), skipinitialspace=True):
            name, util, used, total, temp, power, fan = row
            cards.append(dict(name=name, percent=number(util), used=None if number(used) is None else number(used)*1048576, total=None if number(total) is None else number(total)*1048576, temperature=number(temp), power=number(power), fan=number(fan), vendor='nvidia', memory_kind='dedicated'))
        return dict(available=bool(cards), cards=cards, **(cards[0] if cards else {}))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return dict(available=False, error='NVIDIA telemetry unavailable')

def gpu(intel=None, memory_total=None):
    """NVIDIA through nvidia-smi when present, otherwise an Intel integrated GPU through sysfs and DRM fdinfo."""
    card = nvidia_gpu()
    if card['available'] or intel is None or not intel.available:
        return card
    return intel.sample(memory_total)

SIZE_UNITS = {'B': 1, 'KiB': 1024, 'MiB': 1048576, 'GiB': 1073741824, 'TiB': 1099511627776}

def size(text):
    parts = text.split()
    return int(parts[0]) * SIZE_UNITS.get(parts[1] if len(parts) > 1 else 'B', 1)

def pci_name(vendor, device, database='/usr/share/hwdata/pci.ids'):
    """Device name from the shared PCI ID database; None when missing."""
    try:
        lines = read(database).splitlines()
    except OSError:
        return None
    inside = False
    for line in lines:
        if not line or line.startswith('#'):
            continue
        if not line.startswith('\t'):
            inside = line[:4].lower() == vendor
        elif inside and not line.startswith('\t\t') and line[1:5].lower() == device:
            return line[5:].strip()
    return None

class IntelGpu:
    """Read-only i915/xe telemetry without root: frequency and RC6 residency from sysfs, engine busy time and resident memory from the DRM fdinfo of readable processes."""
    FREQ = (('gt/gt0/rps_act_freq_mhz', 'gt/gt0/rps_RP0_freq_mhz', 'gt/gt0/rc6_residency_ms'),
            ('device/tile0/gt0/freq0/act_freq', 'device/tile0/gt0/freq0/rp0_freq', 'device/tile0/gt0/gtidle/idle_residency_ms'),
            ('gt_act_freq_mhz', 'gt_RP0_freq_mhz', None))

    def __init__(self, drm='/sys/class/drm', proc=PROC, hwmon='/sys/class/hwmon', database='/usr/share/hwdata/pci.ids'):
        self.card = self.pdev = self.name = self.model = None
        self.proc = Path(proc)
        self.act = self.rp0 = self.rc6_path = None
        self.clients, self.time, self.rc6 = {}, None, None
        for card in sorted(Path(drm).glob('card[0-9]*')):
            try:
                if '-' in card.name or read(card/'device/vendor').strip().lower() != '0x8086':
                    continue
                device = read(card/'device/device').strip().lower().removeprefix('0x')
            except OSError:
                continue
            self.card = card
            link = card/'device'
            self.pdev = os.path.basename(os.path.realpath(link)) if link.is_symlink() else None
            self.model = pci_name('8086', device, database)
            short = self.model.rsplit('[', 1)[1].rstrip(']') if self.model and '[' in self.model else None
            self.name = 'Intel ' + short if short else (self.model or 'Intel GPU ' + device)
            for act, rp0, rc6 in self.FREQ:
                if (card/act).exists():
                    self.act, self.rp0, self.rc6_path = card/act, card/rp0, (card/rc6 if rc6 else None)
                    break
            break
        self.package = None
        for label in glob.glob(hwmon + '/hwmon*/temp*_label'):
            try:
                if read(label).strip() == 'Package id 0':
                    self.package = Path(label.replace('_label', '_input'))
                    break
            except OSError:
                pass

    @property
    def available(self):
        return self.card is not None

    def scan(self):
        """{client id: engines ns, memory bytes, capacity} for this card, from the fdinfo of DRM fds this user may read."""
        result = {}
        for entry in os.scandir(self.proc):
            if not entry.name.isdigit():
                continue
            fd_dir = os.path.join(entry.path, 'fd')
            try:
                fds = os.listdir(fd_dir)
            except OSError:
                continue
            for fd in fds:
                try:
                    if not os.readlink(os.path.join(fd_dir, fd)).startswith('/dev/dri/'):
                        continue
                    handle = os.open(os.path.join(entry.path, 'fdinfo', fd), os.O_RDONLY)
                    try:
                        text = os.read(handle, 8192).decode()
                    finally:
                        os.close(handle)
                except (OSError, ValueError):
                    continue
                fields = {}
                for line in text.splitlines():
                    if line.startswith('drm-'):
                        key, _, value = line.partition(':')
                        fields[key] = value.strip()
                pdev = fields.get('drm-pdev')
                if (self.pdev and pdev and pdev != self.pdev) or fields.get('drm-driver') not in ('i915', 'xe'):
                    continue
                cid = fields.get('drm-client-id')
                if not cid:
                    continue
                engines, capacity, memory = {}, {}, 0
                try:
                    for key, value in fields.items():
                        if key.startswith('drm-engine-capacity-'):
                            capacity[key[20:]] = int(value)
                        elif key.startswith('drm-engine-'):
                            engines[key[11:]] = int(value.split()[0])
                        elif key.startswith('drm-resident-'):
                            memory += size(value)
                except (ValueError, IndexError):
                    continue
                result[cid] = dict(engines=engines, capacity=capacity, memory=memory)
        return result

    def read_int(self, path):
        try:
            return int(read(path).strip()) if path else None
        except (OSError, ValueError):
            return None

    def sample(self, memory_total=None):
        now = time.monotonic()
        clients = self.scan()
        elapsed = now - self.time if self.time else None
        busy, capacity = {}, {}
        for cid, c in clients.items():
            old = self.clients.get(cid)
            for engine, ns in c['engines'].items():
                capacity[engine] = max(capacity.get(engine, 1), c['capacity'].get(engine, 1))
                if old and engine in old['engines']:
                    busy[engine] = busy.get(engine, 0) + max(0, ns - old['engines'][engine])
        engines = {}
        if elapsed and elapsed > 0:
            engines = {e: round(min(100, busy[e] / (elapsed * 1e9) / capacity[e] * 100), 1) for e in sorted(busy)}
        rc6 = self.read_int(self.rc6_path)
        awake = None
        if rc6 is not None and self.rc6 is not None and elapsed and elapsed > 0:
            awake = round(max(0, min(100, 100 - (rc6 - self.rc6) / (elapsed * 1000) * 100)), 1)
        temperature = self.read_int(self.package)
        self.clients, self.time, self.rc6 = clients, now, rc6
        card = dict(name=self.name, model=self.model, vendor='intel', percent=max(engines.values()) if engines else None,
                    used=sum(c['memory'] for c in clients.values()), total=memory_total, memory_kind='shared',
                    temperature=None if temperature is None else temperature / 1000, temperature_source='CPU package' if temperature is not None else None,
                    power=None, fan=None, frequency=self.read_int(self.act), max_frequency=self.read_int(self.rp0),
                    engines=engines, awake=awake, clients=len(clients))
        return dict(available=True, cards=[card], **card)

class Fans:
    """System fans from hwmon: RPM, PWM duty when exposed. Discovery globs sysfs once; sampling reads a few files. Two chips reporting one fan (dell_ddv beside dell_smm) merge: the label from one, the PWM from the other."""
    def __init__(self, hwmon='/sys/class/hwmon'):
        self.hwmon = hwmon
        self.discover()

    def discover(self):
        self.entries = []
        for hw in sorted(glob.glob(self.hwmon + '/hwmon*')):
            try:
                chip = read(Path(hw)/'name').strip()
            except OSError:
                continue
            for path in sorted(glob.glob(hw + '/fan*_input')):
                index = Path(path).name[3:-6]
                label, pwm = Path(path.replace('_input', '_label')), Path(hw)/('pwm' + index)
                try:
                    name, labeled = read(label).strip(), True
                except OSError:
                    name, labeled = chip + ' fan' + index, False
                self.entries.append(dict(input=path, pwm=pwm if pwm.exists() else None, name=name, chip=chip, labeled=labeled))

    def sample(self):
        merged = []
        for e in self.entries:
            try:
                rpm = int(read(e['input']))
            except (OSError, ValueError):
                continue
            percent = None
            if e['pwm']:
                try:
                    percent = round(int(read(e['pwm'])) / 255 * 100)
                except (OSError, ValueError):
                    pass
            f = dict(name=e['name'], rpm=rpm, percent=percent, chip=e['chip'], labeled=e['labeled'])
            twin = next((m for m in merged if m['rpm'] == f['rpm'] and m['chip'] != f['chip'] and not (m['labeled'] and f['labeled'])), None)
            if twin is None:
                merged.append(f)
                continue
            if f['labeled'] and not twin['labeled']:
                twin.update(name=f['name'], chip=f['chip'], labeled=True)
            if twin['percent'] is None:
                twin['percent'] = f['percent']
        return [dict((k, v) for k, v in f.items() if k != 'labeled') for f in merged]

def fans(hwmon='/sys/class/hwmon'):
    return Fans(hwmon).sample()

def network():
    result = {}
    for line in read(PROC / 'net/dev').splitlines()[2:]:
        name, fields = line.split(':')
        if name.strip() != 'lo':
            f = fields.split()
            result[name.strip()] = (int(f[0]), int(f[8]))
    return result

def disks():
    rows = []
    for line in read(PROC / 'diskstats').splitlines():
        f = line.split()
        if len(f) >= 14 and Path('/sys/block', f[2]).exists() and not f[2].startswith(('loop', 'ram', 'zram')):
            rows.append((f[2], int(f[5])*512, int(f[9])*512))
    return {name: (r, w) for name, r, w in rows}

def rates(old, new, elapsed):
    return [dict(name=k, read=round(max(0, v[0]-old.get(k, v)[0])/elapsed), write=round(max(0, v[1]-old.get(k, v)[1])/elapsed)) for k, v in new.items()]

def parse_stat(text):
    end = text.rfind(')')
    pid, comm = text[:end+1].split(' (', 1)
    f = text[end+2:].split()
    return dict(pid=int(pid), comm=comm[:-1], ppid=int(f[1]), ticks=int(f[11])+int(f[12]), start=int(f[19]), rss=max(0, int(f[21]))*PAGE)

def process_records():
    result = {}
    for path in PROC.iterdir():
        if not path.name.isdigit():
            continue
        try:
            p = parse_stat(read(path / 'stat'))
            try:
                exe = os.readlink(path / 'exe')
                p['name'] = Path(exe.removesuffix(' (deleted)')).name
            except OSError:
                p['name'] = p['comm']
            p['pss'] = None
            try:
                for line in read(path / 'smaps_rollup').splitlines():
                    if line.startswith('Pss:'):
                        p['pss'] = int(line.split()[1])*1024
                        break
            except OSError:
                pass
            result[p['pid']] = p
        except (OSError, ValueError, IndexError):
            pass  # processes can exit between reads
    return result

def app_name(p, records):
    # Helpers with their own executables belong to the nearest browser/app parent.
    if p['rss'] == 0 and p['pss'] is None:
        return 'Kernel threads' if p['ppid'] == 2 or p['pid'] == 2 else p['name']
    known = ('vivaldi', 'chromium', 'firefox', 'discord', 'spotify', 'code', 'telegram', 'steam', 'chrome', 'electron')
    current = p
    seen = set()
    for _ in range(32):
        if current['pid'] in seen:
            break
        seen.add(current['pid'])
        name = current['name'].lower()
        for app in known:
            if 'crashpad' not in name and (name == app or name.startswith(app + '-') or name.startswith(app + '_') or (app == 'steam' and name == 'steamwebhelper')):
                return app.capitalize() if app != 'code' else 'VS Code'
        current = records.get(current['ppid'])
        if current is None:
            break
    return p['name']

def group_processes(records, previous, elapsed, cores):
    groups = {}
    for p in records.values():
        name = app_name(p, records)
        g = groups.setdefault(name, dict(name=name, cpu=0.0, memory=0, rss=0, pss=0, count=0, rss_fallback=0))
        old = previous.get(p['pid'])
        if old and old['start'] == p['start']:
            g['cpu'] += max(0, p['ticks']-old['ticks'])/HZ/elapsed/cores*100
        # btop's Linux process list reads RSS from stat. Preserve both
        # definitions from the same process set instead of conflating them.
        g['rss'] += p['rss']
        g['memory'] += p['rss']
        if p['pss'] is not None:
            g['pss'] += p['pss']
        g['rss_fallback'] += p['pss'] is None and p['rss'] > 0
        g['count'] += 1
    for g in groups.values():
        g['cpu'] = round(g['cpu'], 2)
        if g['rss_fallback']:
            g['pss'] = None  # partial PSS is unknown, never silently RSS
    return sorted(groups.values(), key=lambda g: (-g['cpu'], -g['memory'], g['name']))

def sensors():
    result = []
    for hw in glob.glob('/sys/class/hwmon/hwmon*'):
        try:
            chip = read(Path(hw)/'name').strip()
        except OSError:
            continue
        if chip.startswith('nvidia'):
            continue
        for path in glob.glob(hw + '/temp*_input'):
            try:
                temp = int(read(path))/1000
                label = Path(path.replace('_input', '_label'))
                name = read(label).strip() if label.exists() else chip
                if -20 <= temp <= 150:
                    result.append(dict(name=name, temperature=temp))
            except (OSError, ValueError):
                pass
    return result

def mounts():
    rows, seen = [], set()
    for line in read(PROC / 'mounts').splitlines():
        source, mount, fs = line.split()[:3]
        mount = mount.replace('\\040', ' ')
        if not source.startswith('/dev/') or mount in seen:
            continue
        seen.add(mount)
        try:
            s = os.statvfs(mount)
            total = s.f_blocks*s.f_frsize
            device_key = (source, total)
            if device_key in seen:
                continue
            seen.add(device_key)
            rows.append(dict(name=mount, total=total, used=(s.f_blocks-s.f_bfree)*s.f_frsize, available=s.f_bavail*s.f_frsize))
        except OSError:
            pass
    return rows

class Sampler:
    def __init__(self):
        self.cpu = cpu_counters()
        self.net = network()
        self.disk = disks()
        self.time = time.monotonic()
        self.processes = {}
        self.process_time = None
        self.history = []
        self.intel = IntelGpu()
        self.fans = Fans()
        self.fan_data = []
        self.count = 0

    def sample(self, detailed=False):
        now = time.monotonic()
        elapsed = max(.001, now-self.time)
        cp = cpu_counters()
        mem = memory()
        card = gpu(self.intel, mem['total'])
        self.count += 1
        if self.count % 30 == 0:
            self.fans.discover()  # hotplugged sensors, once a minute
        if self.count % 3 == 1:
            self.fan_data = self.fans.sample()  # every 6 s: firmware-backed hwmon reads (dell_smm) cost milliseconds each
        net, disk = network(), disks()
        cpu = cpu_percent(self.cpu['cpu'], cp['cpu'])
        self.history = (self.history + [dict(cpu=cpu, ram=mem['percent'], gpu=card.get('percent'))])[-60:]
        result = dict(timestamp=time.time(), cpu=cpu, cores=[cpu_percent(self.cpu.get(k, v), v) for k, v in cp.items() if k != 'cpu'], memory=mem, gpu=card, fans=self.fan_data, network=rates(self.net, net, elapsed), disks=rates(self.disk, disk, elapsed), history=self.history, detailed=detailed, interval=2)
        if detailed:
            records = process_records()
            result.update(apps=group_processes(records, self.processes, max(.001, now-(self.process_time or now)), len(cp)-1), processes_warming=self.process_time is None, sensors=sensors(), mounts=mounts(), load=list(os.getloadavg()), uptime=float(read(PROC/'uptime').split()[0]))
            self.processes, self.process_time = records, now
        else:
            self.processes, self.process_time = {}, None
        self.cpu, self.net, self.disk, self.time = cp, net, disk, now
        return result

def main():
    sampler = Sampler()
    opened = False
    deadline = time.monotonic()+.3
    while True:
        ready, _, _ = select.select([sys.stdin], [], [], max(0, deadline-time.monotonic()))
        if ready:
            command = sys.stdin.readline()
            if not command:
                return
            opened = command.strip() == 'open'
            deadline = min(deadline, time.monotonic())
        if time.monotonic() >= deadline:
            started = time.monotonic()
            try:
                result = sampler.sample(opened)
                result['sample_ms'] = round((time.monotonic()-started)*1000, 1)
                print(json.dumps(result, separators=(',', ':')), flush=True)
            except (OSError, ValueError) as error:
                print(json.dumps(dict(error=type(error).__name__)), flush=True)
            deadline = time.monotonic()+2

if __name__ == '__main__':
    main()
