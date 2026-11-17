# ASUS VivoMini Linux hardware monitoring

Temperature monitoring for ASUS VC66-C2 on Linux, with a small Proxmox VE node-summary extension and documented fan-interface research.

**Temperature monitoring works on the tested machine. Fan control is not implemented or confirmed.** The firmware advertises fan-policy methods, but all tested policy queries returned empty data. This project never writes fan policies, PWM values or EC registers.

繁體中文：已完成 PVE 節點摘要的 CPU、核心、NVMe、SATA 與 ACPI 溫度顯示。目前 BIOS 的風扇查詢回傳全零，尚未找到可驗證的調速介面；沒有加入調速按鈕或修改既有風扇策略。

## Tested configuration

| Component | Version / result |
| --- | --- |
| Machine | ASUS MINIPC VC66-C2, Intel Core i5-10400 |
| BIOS | 1602, dated 2021-12-01 |
| Proxmox VE | 8.4.19 |
| Kernel | 6.8.12-30-pve |
| CPU | Package and six core temperatures, `coretemp` |
| Storage | One NVMe controller, two SATA SSDs (`drivetemp`) |
| ACPI | One `acpitz` zone; its physical location is unspecified |
| Fan | No `fan*_input` or `pwm*` attributes exposed |

Only this PVE version has been tested. The installer refuses layouts whose source anchors do not match. This is a local extension to PVE package files, not an official Proxmox plugin.

## Install on PVE

Copy or clone this repository onto the PVE host. Run as root from its directory:

```sh
python3 pve/install.py install
python3 pve/install.py status
```

Reload the browser and open **Node → Summary**. The extension adds CPU package/core, NVMe, SATA, ACPI and fan rows. A missing sensor is unavailable, never invented as zero. On the tested VC66-C2, the fan row says **No RPM sensor exposed**. Colors use each sensor's kernel-provided maximum/critical thresholds.

The installer loads `coretemp` and `drivetemp`, makes those modules persistent, installs a read-only Perl collector, adds one node-status API hook and loads a separate JavaScript extension. It reloads `pvedaemon` and `pveproxy`; it does not reboot or restart virtual machines. The collector reads existing hwmon files during ordinary PVE status polling. It starts no daemon and runs no hardware-discovery commands.

Files changed or added:

```text
/usr/share/perl5/PVE/API2/Nodes.pm
/usr/share/pve-manager/index.html.tpl
/usr/local/share/pve-local-thermal/LocalThermal.pm
/usr/share/pve-manager/js/local-thermal.js
/etc/modules-load.d/pve-local-thermal.conf
```

Backups and the active manifest are under `/var/lib/pve-local-thermal/`. Each installed file has a recorded SHA-256.

## Remove or upgrade

```sh
python3 pve/install.py remove
```

Reload the browser afterward. Removal restores original files and removes the added files, while retaining backups. Already loaded sensor drivers stay loaded until reboot.

Before upgrading PVE, remove this extension. After the upgrade, review compatibility, run the UI test against the new PVE assets, then reinstall. There is deliberately no automatic package-update hook. If package updates or local edits have already changed an installed file, removal refuses to overwrite it: review the manifest and reconcile the small hooks with the current package version manually. Never restore an old whole-file backup over a newer PVE package without review.

`status` prints `OK` or `CHANGED` for every tracked file. After modifying this project's code, remove the existing installation before reinstalling.

## Fan-interface investigation

See [the VC66-C2 research notes](docs/vc66-c2.md) for the ACPI/WMI method map, firmware results and Ghidra analysis of ASUS Windows libraries.

An optional diagnostic invokes **only the firmware's GetFanPolicy method** through an already available Linux ACPI debugger:

```sh
sudo python3 tools/probe_fan_policy.py --fan-selector 0 1 2 3
```

It is restricted to the VC66-C2 DMI identity and selectors 0–3. It requires `/sys/kernel/debug/acpi/acpidbg` and ACPI debug parameters; the tested PVE kernel provided these already. Do not run it concurrently with another ACPI debugger session. It temporarily enables buffer output and restores debug settings on normal completion or handled errors. Forced termination or a system failure cannot guarantee restoration. This is an occasional diagnostic, not a monitoring loop.

The result is `empty_response` for all-zero buffers, otherwise `unverified_response`. **Both return `control_supported: false`.** Neither a zero error-code field nor the existence of a setter name establishes safe control. Fan selector meanings, mode/profile values and the manual-curve wire format remain unverified.

## Tests

On Linux, from the repository root:

```sh
perl tests/test_thermal.pl
python3 -m unittest discover -s tests -v
```

The collector tests use synthetic sysfs files, including disappearing sensors, decimal thresholds and missing RPM. The probe tests reject malformed buffers and prevent empty firmware responses being mistaken for supported controls.

For the frontend, provide the URL of a PVE installation and a local Chrome/Chromium binary:

```sh
python3 tests/run_ui.py --pve-url https://pve.example:8006 --chrome /usr/bin/chromium
```

For a known local host with a self-signed certificate, add `--insecure`. The runner downloads only unauthenticated UI assets into the ignored `build/` directory. It renders a local fixture with synthetic readings, checks missing sensors, text escaping, updates and reopening, and saves a screenshot. It never signs in or operates a real PVE page. Run with `--strict-control` to verify that reintroducing the original strict-mode bug is detected.

**Ext JS compatibility:** the override must remain non-strict. PVE's Ext JS `callParent()` inspects caller metadata; a strict `initComponent()` breaks node-summary construction even while backend APIs stay fast. The browser test exercises the actual PVE class to catch this failure.

## Contributing

Useful evidence includes the board/BIOS/kernel version, exposed hwmon attributes, and sanitized diagnostic results. Do not submit credentials, cookies, serial numbers, host addresses, complete firmware dumps or proprietary ASUS binaries. A control implementation needs verified selector/enum semantics, observable readback and a demonstrated restoration path before exposing setters.

Original code and documentation are MIT licensed. Vendor software and downloaded PVE test assets are not distributed by this repository and retain their respective licenses.
