#!/usr/bin/env python3
"""Query GFAN on an ASUS VC66-C2; never call fan setters or write EC registers.

Requires root and the Linux ACPI debugger. Temporarily enables debugger buffer
output and restores debug parameters on exit. Not suitable for periodic polling.
"""
import argparse
import json
import os
from pathlib import Path
import re
import select
import time

DEBUGGER = Path('/sys/kernel/debug/acpi/acpidbg')
PARAMETERS = Path('/sys/module/acpi/parameters')

def parameter_value(text, name):
    match = re.search(r'^' + re.escape(name) + r'\s*=\s*(0x[0-9a-fA-F]+)', text, re.M)
    if not match:
        raise ValueError(f'Cannot parse {name}; refusing to change debugger flags')
    return int(match[1], 16)

def parse_response(text, selector):
    length = re.search(r'\[Buffer\] Length ([0-9A-Fa-f]+)', text)
    if not length:
        raise ValueError('Firmware did not return a buffer: ' + text.strip())
    data = bytearray()
    for line in text.splitlines():
        if re.match(r'^\s*[0-9A-Fa-f]{4}:', line):
            payload = line.split(':', 1)[1].split('//', 1)[0]
            data.extend(int(v, 16) for v in re.findall(r'\b[0-9A-Fa-f]{2}\b', payload))
    expected = int(length.group(1), 16)
    if expected == 0 or len(data) != expected:
        raise ValueError(f'Incomplete buffer: expected {expected} bytes, received {len(data)}')
    return {
        'interface': 'ASUSManagement WMI fan policy (not direct EC control)',
        'fan_selector': selector,
        'method': r'\AMW0.GFAN',
        'length': len(data),
        # A zero error-code DWORD inside an entirely empty response is NOT
        # evidence of working policy support. Do not expose setters from it.
        'status': 'empty_response' if not any(data) else 'unverified_response',
        'raw_hex': data.hex(),
        'control_supported': False,
    }

def read_until_prompt(fd, timeout=8):
    output = bytearray()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], max(0, deadline - time.monotonic()))
        if not ready:
            break
        try:
            chunk = os.read(fd, 4096)
        except BlockingIOError:
            continue
        if not chunk:
            raise RuntimeError('ACPI debugger closed the connection')
        output.extend(chunk)
        if output.endswith(b'\n- '):
            return output.decode('ascii', errors='replace')
        if len(output) > 65536:
            raise RuntimeError('Unexpectedly large debugger output')
    raise TimeoutError('ACPI debugger did not return to its prompt')

def probe(selectors):
    board = Path('/sys/class/dmi/id/board_name').read_text().strip()
    vendor = Path('/sys/class/dmi/id/sys_vendor').read_text().strip()
    if board != 'VC66-C2' or vendor != 'ASUSTeK COMPUTER INC.':
        raise RuntimeError('This experimental probe is restricted to ASUS VC66-C2')
    if any(type(v) is not int or v not in range(4) for v in selectors):
        raise ValueError('Only selectors 0 through 3 have been investigated')
    previous = {name: parameter_value((PARAMETERS / name).read_text(), name)
                for name in ('debug_layer', 'debug_level')}
    fd = None
    console_level = None
    try:
        (PARAMETERS / 'debug_layer').write_text(hex(previous['debug_layer'] | 0x200))
        fd = os.open(DEBUGGER, os.O_RDWR | os.O_NONBLOCK)
        read_until_prompt(fd)
        os.write(fd, b'level\n')
        levels = read_until_prompt(fd)
        match = re.search(r'console output is:\s*([0-9A-Fa-f]+)', levels)
        if not match:
            raise RuntimeError('Cannot preserve debugger console verbosity')
        console_level = int(match[1], 16)
        # Set the console's table-output bit for this debugger session.
        os.write(fd, f'level {console_level | 0x2000:X} console\n'.encode('ascii'))
        read_until_prompt(fd)
        results = []
        for selector in selectors:
            command = f'evaluate \\AMW0.GFAN ({selector:02X})\n'.encode('ascii')
            os.write(fd, command)
            results.append(parse_response(read_until_prompt(fd), selector))
        return {'board': board, 'bios': Path('/sys/class/dmi/id/bios_version').read_text().strip(),
                'results': results}
    finally:
        try:
            if fd is not None:
                try:
                    if console_level is not None:
                        os.write(fd, f'level {console_level:X} console\n'.encode('ascii'))
                        read_until_prompt(fd, timeout=2)
                finally:
                    os.close(fd)
        finally:
            for name, value in previous.items():
                (PARAMETERS / name).write_text(hex(value))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fan-selector', type=int, choices=range(4), nargs='+', default=[0])
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() != 0:
        parser.error('Run on the PVE/Linux host as root')
    print(json.dumps(probe(args.fan_selector), indent=2))

if __name__ == '__main__':
    main()
