# Tests

On Linux, from the repository root:

```sh
perl tests/test_thermal.pl
python3 -m unittest discover -s tests -v
```

The collector tests use synthetic sysfs files, including disappearing sensors, decimal thresholds and missing RPM. The probe tests reject malformed buffers and prevent empty firmware responses being mistaken for supported controls.

EC tests use fake registers and temporary files. They check profile selection, torn RPM readings, bank changes, write targets/readback, restoration after errors or interruption, and closing the parent descriptor before unloading the module. Watchdog tests fork real processes over synthetic EC files to exercise commit, timeout and parent-pipe disconnection. They do not load kernel modules or access hardware. Run on Linux to include all POSIX cases; some tests are skipped on Windows.

Cache tests verify atomic replacement, preservation on failed publication, freshness, incompatible data, malformed/oversized JSON, symlinks and FIFOs. The Perl FIFO check has a deadline: a bad cache must not block the node API. The UI fixture exercises actual PVE classes, with fake control/task responses, including duplicate clicks, failed and timed-out tasks, insufficient privilege, stale readings, view reopening and late callbacks after destruction. Use `--view-width 600` to check wrapping within a narrower PVE status component.

Deployment verification on the tested host passed 23 Python tests and 25 Perl assertions. Live checks covered read-only account controls, summary reload without JavaScript errors, an authorized PVE task selecting full speed (~5,300 RPM) and returning to Normal, rejection of invalid modes and stale-cache writes, and monitor interruption/recovery. Cookie-authenticated writes without CSRF were rejected. Under three concurrent requests, cluster/node HTTP status requests remained below 40 ms in the measured run. These timings are observations on the test host, not latency guarantees.

For the frontend, provide the URL of a PVE installation and a local Chrome/Chromium binary:

```sh
python3 tests/run_ui.py --pve-url https://pve.example:8006 --chrome /usr/bin/chromium
```

For a known local host with a self-signed certificate, add `--insecure`. The runner downloads only unauthenticated UI assets into the ignored `build/` directory. It renders a local fixture with synthetic readings, checks missing sensors, text escaping, updates and reopening, and saves a screenshot. It never signs in or operates a real PVE page. Run with `--strict-control` to verify that reintroducing the original strict-mode bug is detected.

**Ext JS compatibility:** the override must remain non-strict. PVE's Ext JS `callParent()` inspects caller metadata; a strict `initComponent()` breaks node-summary construction even while backend APIs stay fast. The browser test exercises the actual PVE class to catch this failure.
