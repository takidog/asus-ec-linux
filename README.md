# ASUS EC fan control for Linux

**English** | [繁體中文](README.zh-TW.md)

Read fan RPM and select firmware fan modes on ASUS systems with supported embedded-controller (EC) layouts. The current implementation targets an ASUS ITE IT8225 firmware interface, **tested on the VivoMini VC66-C2 with BIOS 1602**. Support is based on a verified board/BIOS register map; sharing an EC chip does not establish compatibility.

On the tested system, selecting full speed increased the CPU fan from **3,237 RPM to approximately 5,300 RPM**. Restoring Normal mode returned it to **3,267 RPM** after settling. No reboot or BIOS-variable write was needed.

## Features

- Read the CPU fan's RPM and current EC mode.
- Select **Normal** or **full speed** (BIOS QFan disabled).
- Run a brief full-speed test that restores the original mode automatically.
- Optional [Proxmox VE temperature integration](docs/pve.md) for CPU, NVMe, SATA and ACPI sensors.

This is experimental hardware support. Quiet mode is identified in firmware but is not exposed as a setter because it has not been tested. Arbitrary PWM percentages and custom fan curves are not implemented.

## Quick start

Requires Linux, Python 3.9+, root, the kernel's `ec_sys` module, and mounted debugfs exposing `/sys/kernel/debug/ec/ec0/io` after module loading. Use the host, not a container or VM.

```sh
git clone https://github.com/takidog/asus-ec-linux.git
cd asus-ec-linux

# Read RPM and mode. Does not write EC registers.
sudo python3 tools/asus_ec.py status

# Full speed for 10 seconds, then restore the original mode.
sudo python3 tools/asus_ec.py test-full-speed --seconds 10

# Select a mode until firmware changes it or the machine restarts.
sudo python3 tools/asus_ec.py set-mode full-speed
sudo python3 tools/asus_ec.py set-mode normal
```

Each reading is a JSON line, for example:

```json
{"stage":"status","profile":"asus-ite8225-vc66-c2-1602","mode":"normal","mode_raw":0,"fan_rpm":3267}
```

`set-mode` changes runtime EC state. It does not save a BIOS setting, install a service, or reapply the mode after reboot/resume. Fan inertia means the immediate RPM after a mode change will differ from its settled speed.

## Compatibility and safeguards

| System / firmware | RPM | Normal / full speed | Quiet | Custom curve |
| --- | --- | --- | --- | --- |
| ASUS VC66-C2, BIOS 1602 | Tested | Tested | Firmware definition only | Unimplemented |
| ASUS VC66-C2, BIOS 1603 | Not tested; relevant sensor/EC/WMI modules match 1602 | Not enabled | Not tested | Unimplemented |
| Other ASUS boards with ITE IT8225 | Register map unverified | Not enabled | Not tested | Unimplemented |

The tool selects an explicit DMI vendor/board/BIOS profile and refuses unknown combinations. There is no force-model or arbitrary-register option. New compatible boards can be added as separately reviewed profiles; the project's scope is not limited to the first tested machine.

Reads and writes require EC bank zero; the tool never switches banks. Only the verified mode byte is writable. A write requires the original mode to be Normal or full speed so it can be restored using a tested value. The tool checks readback and uses a separate watchdog process to restore on failed operations, parent disconnection or timeout. Successful `set-mode` operations intentionally retain the requested mode.

If `ec_sys` is already loaded, status preserves it and mode changes refuse to reconfigure it. Otherwise the tool loads the module for the operation, disables write access and unloads it afterward. Temporary tests accept 1–30 seconds. A process lock prevents overlapping instances of this tool; it cannot coordinate firmware or other EC utilities. Avoid concurrent EC tools. Restoration is best effort if the kernel, firmware or machine itself fails; bank checks cannot make multiple EC transactions atomic.

## Firmware and Windows software research

The working path was recovered from the ASUS BIOS fan-setting callback and sensor provider with Ghidra, then checked against real RPM changes on Linux. It uses the kernel's ACPI EC transport through `ec_sys`; no custom raw-port driver is needed.

The advertised ASUSManagement WMI fan-policy methods are stubs in the examined firmware: getters leave the policy empty and setters return an unsupported result. Windows libraries provide WMI/COM wrappers, but their presence does not make those firmware methods functional.

See [the VC66-C2 case study](docs/vc66-c2.md) for the register map, firmware identifiers, Windows call chains, other-board evidence and remaining unknowns. The optional `tools/probe_fan_policy.py` is a **WMI-only diagnostic**; its `control_supported: false` result does not describe the separate, working EC path.

## PVE integration and development

The [PVE extension](docs/pve.md) is optional and independent of the CLI. It displays temperatures from standard hwmon drivers. It does not currently include direct EC RPM readings or fan-control buttons. Tested on PVE 8.4.19 / Linux 6.8.12-30-pve.

Run the hardware-free tests on Linux:

```sh
python3 -m unittest discover -s tests -v
perl tests/test_thermal.pl
```

See [testing notes](docs/testing.md) for frontend checks. EC tests cover model/BIOS guards, torn readings, bank changes, exact write targets, restoration after errors, and independent-process watchdog timeout/disconnection. Tests never access real hardware.

Contributions for other ASUS systems should include the board/BIOS/kernel version, the source of the register map, sanitized RPM/mode observations, and a demonstrated restoration path. A matching chip name alone is insufficient. Do not submit credentials, cookies, serial numbers, host addresses, complete firmware dumps or proprietary ASUS binaries.

Original code and documentation are MIT licensed. Vendor software and downloaded PVE test assets are not distributed and retain their respective licenses.
