#!/usr/bin/env python3
"""Install/remove the small PVE hooks with hash-guarded rollback.

Run as root on the PVE host. Package upgrades may overwrite hooks; review and
rerun after upgrades. This deliberately does not add automatic upgrade hooks.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
STATE = Path('/var/lib/pve-local-thermal')
MODULE = Path('/usr/local/share/pve-local-thermal/LocalThermal.pm')
JAVASCRIPT = Path('/usr/share/pve-manager/js/local-thermal.js')
NODES = Path('/usr/share/perl5/PVE/API2/Nodes.pm')
TEMPLATE = Path('/usr/share/pve-manager/index.html.tpl')
MODULES = Path('/etc/modules-load.d/pve-local-thermal.conf')
API_ANCHOR = '        $res->{cpuinfo} = PVE::ProcFSTools::read_cpuinfo();\n'
API_HOOK = '''
        # BEGIN pve-local-thermal
        $res->{localthermal} = {};
        eval {
            require '/usr/local/share/pve-local-thermal/LocalThermal.pm';
            $res->{localthermal} = PVE::LocalThermal::collect();
        };
        # END pve-local-thermal
'''
WEB_ANCHOR = '    <script type="text/javascript" src="/pve2/js/pvemanagerlib.js?ver=[% version %]"></script>\n'
WEB_HOOK = '    <script type="text/javascript" src="/pve2/js/local-thermal.js?v=2"></script>\n'

def digest(data):
    return hashlib.sha256(data).hexdigest()

def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.chmod(temp, 0o644)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def reload_services():
    subprocess.run(['systemctl', 'reload', 'pvedaemon', 'pveproxy'], check=True)

def restore(manifest, check_hash=True):
    if check_hash:
        for record in manifest['files']:
            path = Path(record['path'])
            if not path.exists() or digest(path.read_bytes()) != record['installed_sha256']:
                raise SystemExit(f'Refusing rollback: {path} changed since installation; review manually.')
    for record in reversed(manifest['files']):
        path = Path(record['path'])
        if record['backup']:
            write(path, Path(record['backup']).read_bytes())
        else:
            path.unlink(missing_ok=True)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['install', 'remove', 'status'])
    args = p.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Run as root.')
    active = STATE / 'active.json'
    if args.action == 'status':
        if not active.exists():
            print('Not installed.')
            return
        manifest = json.loads(active.read_text())
        for record in manifest['files']:
            path = Path(record['path'])
            ok = path.exists() and digest(path.read_bytes()) == record['installed_sha256']
            print(('OK ' if ok else 'CHANGED ') + str(path))
        return
    if args.action == 'remove':
        if not active.exists():
            raise SystemExit('No active installation.')
        restore(json.loads(active.read_text()))
        active.unlink()
        reload_services()
        print('Removed integration. Backups retained; loaded sensor drivers remain until reboot.')
        return
    if active.exists():
        raise SystemExit('Already installed. Use status; remove before reinstalling.')
    original = NODES.read_text()
    template = TEMPLATE.read_text()
    if original.count(API_ANCHOR) != 1 or template.count(WEB_ANCHOR) != 1:
        raise SystemExit('PVE source anchors do not match. No changes made.')
    if '# BEGIN pve-local-thermal' in original or 'local-thermal.js' in template:
        raise SystemExit('Existing hook found without manifest. Review manually.')
    subprocess.run(['perl', '-c', str(HERE / 'LocalThermal.pm')], check=True)
    changes = {
        MODULE: (HERE / 'LocalThermal.pm').read_bytes(),
        JAVASCRIPT: (HERE / 'local-thermal.js').read_bytes(),
        MODULES: b'# Read-only CPU and SATA temperature sensors\ncoretemp\ndrivetemp\n',
        NODES: original.replace(API_ANCHOR, API_ANCHOR + API_HOOK).encode(),
        TEMPLATE: template.replace(WEB_ANCHOR, WEB_ANCHOR + WEB_HOOK).encode(),
    }
    # Refuse to take over unrelated local integration files.
    for path in (MODULE, JAVASCRIPT, MODULES):
        if path.exists():
            raise SystemExit(f'{path} already exists. No changes made.')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup_dir = STATE / ('backup-' + stamp)
    backup_dir.mkdir(parents=True, mode=0o700)
    manifest = {'created_utc': stamp, 'files': []}
    for index, (path, data) in enumerate(changes.items()):
        backup = backup_dir / f'{index}-{path.name}' if path.exists() else None
        if backup:
            shutil.copy2(path, backup)
        manifest['files'].append({'path': str(path), 'backup': str(backup) if backup else None,
                                  'installed_sha256': digest(data)})
    write(backup_dir / 'manifest.json', json.dumps(manifest, indent=2).encode())
    try:
        for path, data in changes.items():
            write(path, data)
        # Load the API exactly as pvesh does; catches Perl/registration errors.
        subprocess.run(['pvesh', 'get', '/nodes/localhost/status', '--output-format', 'json'],
                       check=True, stdout=subprocess.DEVNULL, timeout=30)
        subprocess.run(['modprobe', 'coretemp'], check=True)
        subprocess.run(['modprobe', 'drivetemp'], check=True)
        reload_services()
    except BaseException:
        restore(manifest, check_hash=False)
        reload_services()
        raise
    write(active, json.dumps(manifest, indent=2).encode())
    print(f'Installed. Backup: {backup_dir}. Reload browser to see readings.')

if __name__ == '__main__':
    main()
