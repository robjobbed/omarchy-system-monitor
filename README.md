# System Monitor

Read-only Omarchy/Quickshell bar widget for CPU, RAM, GPU (NVIDIA, or Intel integrated graphics), system fans, grouped applications, temperatures, storage and network rates.

Plugin ID: `cynricantao.system-monitor`. Requires Omarchy's native `qs.Ui`/`qs.Commons` APIs and `/usr/bin/python3` (standard library only). NVIDIA metrics optionally use `/usr/bin/nvidia-smi`. Intel integrated GPUs (i915 or xe driver) are read from sysfs and DRM fdinfo without any extra tool; see [Intel GPUs](#intel-gpus). Missing or unsupported telemetry is shown as unavailable. No root privileges, separate service or Python packages are needed. AMD adapters and per-application GPU usage are not implemented.

## Screenshots

These are captures of the actual QML interface in an isolated preview session,
using **synthetic demonstration telemetry**. Hardware labels, application names,
resource percentages and storage values are examples—not the maintainer's
computer. No personal desktop, real process list or private mount path is shown.

<table>
<tr>
<td><img src="docs/images/overview.png" width="440" alt="System Monitor dashboard with example CPU RAM GPU histories and grouped applications"></td>
<td><img src="docs/images/storage.png" width="440" alt="System Monitor Storage tab showing a synthetic system filesystem capacity bar"></td>
</tr>
<tr><td><strong>Processes:</strong> resource cards and grouped applications.</td><td><strong>Storage:</strong> filesystem usage while the resource cards remain visible.</td></tr>
</table>

## Quick walkthrough

1. **Open the dashboard:** click any RAM, CPU or GPU bar icon/percentage.
2. **Inspect applications:** Processes shows the top five grouped applications.
   Use RAM/CPU to change sorting, RSS/PSS to compare memory accounting, and See
   all to expand the list. Missing PSS remains unavailable rather than becoming RSS.
3. **Explore other views:** Temps shows available sensors; Storage shows
   filesystem capacity; Network shows per-interface traffic rates and histories.
4. **Open Details:** inspect available RAM/swap, CPU cores, disk rates, load,
   uptime and metric interpretation notes in the scrollable detail view.
5. **Close with Escape or an outside click:** detailed process scans stop when
   closed; the bar continues its lightweight resource sampling.

## Install, update and remove

Review the code before enabling it: Omarchy plugins run unsandboxed as your user.

```sh
omarchy plugin add https://github.com/cynricantao/omarchy-system-monitor.git --enable
omarchy plugin update cynricantao.system-monitor
omarchy plugin remove cynricantao.system-monitor
```

No install hook or separate service is required; the shell starts the read-only
collector when the widget loads. Removing the plugin stops its widget/child collector;
there is no plugin-created persistent monitoring history to erase.

## Use

Click a RAM/CPU/GPU bar icon or percentage to toggle the popup; Escape or an outside click closes it. The default Processes view shows five grouped applications; See all expands the list. RAM/CPU switches sorting; RSS/PSS switches the memory definition. Temperatures, Storage, Network and Details expose additional metrics. Popup width targets 440 scaled pixels; height is capped at the smaller of 460 scaled pixels and 44% of the active screen height. Scroll longer lists inside the popup.

## Metrics and sampling

- CPU: `/proc/stat` interval deltas excluding idle and iowait; normalized to whole-machine 0–100%. Guest time is not double-counted.
- RAM: `(MemTotal - MemAvailable) / MemTotal`, treating reclaimable cache as available.
- Application CPU: summed user/system tick deltas normalized by logical core count. Opening requires two samples; PID reuse is detected and exited processes are not retained.
- RSS: summed resident pages from `/proc/PID/stat`. Shared pages count in each process, so group totals can exceed attributable physical memory. PSS: summed readable `smaps_rollup` proportional memory; a missing PSS for any nonzero-RSS process makes that group's PSS unavailable, never a mixture of RSS and PSS. Application totals need not equal system-used RAM.
- Common browser/Steam helpers join their application group. Other executables group by basename; interpreter-based programs may share a Python/Node group. Kernel threads are grouped.
- GPU: NVIDIA utilization, VRAM and sensor values through `nvidia-smi`, with unavailable values when unsupported. Without `nvidia-smi`, the first Intel DRM card is used instead (below).
- Fans: every hwmon `fan*_input`, with the hwmon label when there is one and the PWM duty as a percentage when `pwm<N>` is readable. Two chips reporting one fan at the same RPM (Dell's `dell_ddv` beside `dell_smm`) merge into one entry carrying the label from one and the PWM from the other. The first fan is shown under the GPU card; all of them in Temps.
- Network: per-interface receive/transmit counter deltas; tunnels can overlap physical traffic. Disk rates use whole block devices, not partitions. Storage deduplicates same-source/same-capacity mounts.
- One Python collector samples every two seconds **after collection**. Process and smaps scans occur only while the popup is open. CPU/RAM/GPU history keeps 60 samples; per-interface network history keeps 60 points updated only while open. Histories are in memory. Detail cost depends on process count and memory maps; no performance guarantees or published benchmark claims are made.
- Bar metrics become stale after eight seconds without a successful sample. Collector restart attempts occur every ten seconds after failure. Animations are finite.

## Intel GPUs

Integrated Intel graphics has no `nvidia-smi` equivalent, and `intel_gpu_top` needs perf privileges, so the collector reads what the kernel exposes to an ordinary user:

- **Busy %** is the busiest engine (render, copy, video, video-enhance) over the sample interval, summed across the DRM clients whose `/proc/PID/fdinfo` this user can read, normalized by engine capacity. Other users' GPU work is invisible, so a system with another active seat under-reports. The first sample has no delta and shows `—`.
- **Awake %** (Details) is the share of the interval the GPU spent out of RC6 power saving, from `rc6_residency_ms`. It is system-wide and usually a little above the busy figure.
- **Memory** is shared system RAM: the sum of `drm-resident-*` across clients, over total RAM. There is no VRAM on an integrated GPU.
- **Frequency** is the current and RP0 (maximum) GT frequency from sysfs. An idle GPU reports 0 MHz.
- **Temperature** is the CPU package sensor (`coretemp`, `Package id 0`): the GPU shares the die and has no sensor of its own. The Details note says so.
- **Power** is unavailable: the RAPL `uncore` energy counter is root-only on current kernels.
- The card name comes from `/usr/share/hwdata/pci.ids` (the bracketed marketing name, e.g. Iris Xe Graphics), with a fallback to the PCI device id.

The fdinfo scan reads about a thousand small files and costs roughly 10–15 ms per two-second sample on a 12-thread laptop. Both i915 (`gt/gt0/`) and xe (`device/tile0/gt0/`) sysfs layouts are recognized; only i915 has been tested, on an Alder Lake Iris Xe.

## Local management and IPC

Once installed through Omarchy's plugin workflow:

```sh
omarchy plugin enable cynricantao.system-monitor --section right
omarchy plugin disable cynricantao.system-monitor
omarchy-shell cynricantao.system-monitor status
omarchy-shell cynricantao.system-monitor open
omarchy-shell cynricantao.system-monitor close
omarchy-shell cynricantao.system-monitor toggle
omarchy-shell cynricantao.system-monitor view applications
omarchy-shell cynricantao.system-monitor view processes
omarchy-shell cynricantao.system-monitor view temperatures
omarchy-shell cynricantao.system-monitor view storage
omarchy-shell cynricantao.system-monitor view network
omarchy-shell cynricantao.system-monitor view details
omarchy-shell cynricantao.system-monitor sort cpu
omarchy-shell cynricantao.system-monitor sort memory
omarchy-shell cynricantao.system-monitor memory rss
omarchy-shell cynricantao.system-monitor memory pss
```

`status` returns only popup/collector health and selected UI state, not telemetry. `view all` is an alias for applications; unknown views select processes, unknown sorts select memory, and unknown memory modes select RSS. Controls change presentation and whether detailed sampling runs, not monitored applications or system settings. These are **unsandboxed local shell IPC**, not authenticated remote APIs. See [SECURITY.md](SECURITY.md).

## Privacy

No analytics, telemetry uploads, HTTP requests, credentials, command-line arguments, environment variables or process-memory contents are collected. The collector reads system counters, hardware sensor labels, GPU model/metrics, executable **basenames**, process IDs/parent IDs/timing/resident memory and PSS totals. It resolves executable symlinks internally but does not emit their full paths. Opening the popup additionally reads mount paths/capacity, load and uptime. Process/mount/interface names can reveal private activity even without command lines.

Snapshots travel over a local child-process stdout pipe into the shell; transient process metadata and histories remain in memory, not plugin-created files. Closing clears detailed snapshots/process baselines; metric and network histories remain until the shell exits. Existing OS/shell logs or crash dumps may retain data independently. Screenshots and copied output can disclose activity: review/redact them before sharing. The plugin shares the shell user's permissions and is not a security boundary.

## Verification

Run from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -v
omarchy plugin validate "$PWD"
```

Tests cover accounting and collector/IPC/source security contracts. Some source checks are structural and GPU tests use mocked subprocess responses; neither proves live QML rendering. Plugin validation checks manifest compatibility, not runtime or visual acceptance. Validate live behavior separately before release; this public candidate has not been installed or used to restart the shell during preparation.

## License and compatibility

MIT; see [LICENSE](LICENSE). `MonitorPopup.qml` derives from Omarchy's native `shell/Ui/KeyboardPanel.qml`, copyright David Heinemeier Hansson. Its retained MIT notice is in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). The compatibility copy adds `qs.Ui`, a fixed dark background and square corners; review it after shell API updates. System Monitor does not provide process killing or btop's full inspection features.
