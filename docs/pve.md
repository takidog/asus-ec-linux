# Proxmox VE temperature integration

Tested with PVE 8.4.19 and Linux 6.8.12-30-pve on the ASUS VC66-C2. The installer refuses source layouts whose anchors do not match. This changes local PVE package files; it is not an official Proxmox plugin.

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

`status` prints `OK` or `CHANGED` for every tracked file. After modifying the extension's code, remove the existing installation before reinstalling.

The EC fan tool is independent of this extension. Its RPM reading is not yet included in the PVE collector, which reads standard hwmon only. Fan writes are never performed during node-status polling.

See [tests and frontend compatibility](testing.md).
