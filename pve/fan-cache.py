#!/usr/bin/env python3
"""Isolate EC reads from PVE requests; publish a small atomic status snapshot."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
STATE = Path('/run/asus-ec-fan')
source = HERE / 'asus_ec.py'
if not source.exists():
    source = HERE.parent / 'tools/asus_ec.py'
spec = importlib.util.spec_from_file_location('asus_ec', source)
fan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fan)


def publish(reading, directory=STATE):
    payload = {'updated_at': time.time(), **reading}
    fd, temp = tempfile.mkstemp(prefix='.status-', dir=directory)
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(payload, handle)
        os.chmod(temp, 0o644)
        os.replace(temp, directory / 'status.json')
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def sample():
    with fan.exclusive_access(), fan.ec_session(fan.select_profile()) as ec:
        publish(ec.status())


def set_mode(mode):
    # Wait briefly for an in-flight sample, without allowing queued controls.
    deadline = time.monotonic() + 2
    while True:
        try:
            with fan.exclusive_access():
                profile = fan.select_profile()
                with fan.ec_session(profile, True) as ec:
                    fan.change_mode(ec, fan.WRITABLE_MODES[mode])
                with fan.ec_session(profile) as ec:
                    reading = ec.status()
                    if reading['mode'] != mode:
                        raise RuntimeError('Fan mode changed before final readback')
                    publish(reading)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise RuntimeError('Fan interface is busy; try again after the current operation') from None
            time.sleep(0.1)


def run_sample(command=None, timeout=3, grace=1):
    command = command or [sys.executable, str(HERE / 'fan-cache.py'), 'sample']
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    expired = False
    try:
        try:
            _, error = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            expired = True
            # Give ec_session's signal handler time to unload its own module.
            process.terminate()
            try:
                _, error = process.communicate(timeout=grace)
            except subprocess.TimeoutExpired:
                process.kill()
                _, error = process.communicate()
        return process.returncode, error, expired
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=grace)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()


def serve():
    # Hardware can stall in the kernel. A separate sample process keeps it out
    # of PVE workers. A stalled service only makes the cache stale, never blocks
    # the node API. Do not launch another sampler until the previous one exits.
    while True:
        code, error, expired = run_sample()
        if expired:
            print('EC sample timed out; PVE will mark old readings unavailable', file=sys.stderr, flush=True)
        elif code:
            print(error.strip()[:500], file=sys.stderr, flush=True)
        time.sleep(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('serve')
    commands.add_parser('sample')
    setter = commands.add_parser('set-mode')
    setter.add_argument('mode', choices=tuple(fan.WRITABLE_MODES))
    args = parser.parse_args()
    for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, fan.interrupted)
    try:
        {'serve': serve, 'sample': sample, 'set-mode': lambda: set_mode(args.mode)}[args.command]()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
