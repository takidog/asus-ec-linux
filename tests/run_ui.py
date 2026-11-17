#!/usr/bin/env python3
"""Test the extension against actual PVE UI classes using a local fake-data page."""
import argparse
import html
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import tempfile
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ASSETS = {
    'ext.js': '/pve2/ext6/ext-all-debug.js',
    'charts.js': '/pve2/ext6/charts-debug.js',
    'proxmoxlib.js': '/proxmoxlib.js',
    'pve.js': '/pve2/js/pvemanagerlib.js',
    'theme.css': '/pve2/ext6/theme-crisp/resources/theme-crisp-all.css',
    'theme-crisp-all_1.css': '/pve2/ext6/theme-crisp/resources/theme-crisp-all_1.css',
    'theme-crisp-all_2.css': '/pve2/ext6/theme-crisp/resources/theme-crisp-all_2.css',
    'pve.css': '/pve2/css/ext6-pve.css',
    'pmx.css': '/pwt/css/ext6-pmx.css',
}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pve-url', required=True)
    parser.add_argument('--chrome', required=True, help='Path to Chrome or Chromium')
    parser.add_argument('--insecure', action='store_true', help='Accept a self-signed PVE TLS certificate')
    parser.add_argument('--strict-control', action='store_true', help='Verify the test catches the strict-mode regression')
    args = parser.parse_args()
    parsed = urllib.parse.urlsplit(args.pve_url)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password:
        parser.error('--pve-url must be an HTTPS URL without embedded credentials')
    base = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, '', '', ''))
    output = ROOT / 'build' / 'ui'
    output.mkdir(parents=True, exist_ok=True)
    context = ssl._create_unverified_context() if args.insecure else ssl.create_default_context()
    for name, path in ASSETS.items():
        with urllib.request.urlopen(base + path, context=context, timeout=20) as response:
            (output / name).write_bytes(response.read())
    shutil.copyfile(ROOT / 'tests' / 'ui.html', output / 'index.html')
    javascript = (ROOT / 'pve' / 'local-thermal.js').read_text(encoding='utf-8')
    if args.strict_control:
        javascript = javascript.replace('(function () {', "(function () {\n'use strict';", 1)
    (output / 'local-thermal.js').write_text(javascript, encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='thermal-ui-') as profile:
        result = subprocess.run([
            args.chrome, '--headless', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
            '--user-data-dir=' + profile, '--window-size=1000,800', '--virtual-time-budget=4000',
            '--screenshot=' + str(output / 'summary.png'), '--dump-dom', (output / 'index.html').as_uri(),
        ], capture_output=True, timeout=40)
    dom = result.stdout.decode('utf-8', errors='replace')
    (output / 'rendered.html').write_text(dom, encoding='utf-8')
    match = re.search(r'<pre id="result">(.*?)</pre>', dom, re.S)
    message = html.unescape(match[1]) if match else 'FAIL: browser produced no test result'
    if args.strict_control:
        if result.returncode == 0 and message.startswith('FAIL:') and '$owner' in message:
            print('PASS: strict-mode regression was detected by the real Ext JS class')
            return
        raise SystemExit('FAIL: strict-mode control did not reproduce the expected error\n' + message)
    if result.returncode != 0 or not message.startswith('PASS:') or 'ERROR:' in message:
        raise SystemExit(message)
    print(message)
    print('Screenshot:', output / 'summary.png')

if __name__ == '__main__':
    main()
