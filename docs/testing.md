# Tests

On Linux, from the repository root:

```sh
perl tests/test_thermal.pl
python3 -m unittest discover -s tests -v
```

The collector tests use synthetic sysfs files, including disappearing sensors, decimal thresholds and missing RPM. The probe tests reject malformed buffers and prevent empty firmware responses being mistaken for supported controls.

EC tests use fake registers and temporary files. They check profile selection, torn RPM readings, bank changes, write targets/readback, restoration after errors or interruption, and closing the parent descriptor before unloading the module. Watchdog tests fork real processes over synthetic EC files to exercise commit, timeout and parent-pipe disconnection. They do not load kernel modules or access hardware. Run on Linux to include all POSIX cases; some tests are skipped on Windows.

For the frontend, provide the URL of a PVE installation and a local Chrome/Chromium binary:

```sh
python3 tests/run_ui.py --pve-url https://pve.example:8006 --chrome /usr/bin/chromium
```

For a known local host with a self-signed certificate, add `--insecure`. The runner downloads only unauthenticated UI assets into the ignored `build/` directory. It renders a local fixture with synthetic readings, checks missing sensors, text escaping, updates and reopening, and saves a screenshot. It never signs in or operates a real PVE page. Run with `--strict-control` to verify that reintroducing the original strict-mode bug is detected.

**Ext JS compatibility:** the override must remain non-strict. PVE's Ext JS `callParent()` inspects caller metadata; a strict `initComponent()` breaks node-summary construction even while backend APIs stay fast. The browser test exercises the actual PVE class to catch this failure.
