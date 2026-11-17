#!/usr/bin/env python3
"""Read fan RPM and select verified ASUS EC fan modes on Linux.

Board/BIOS profiles are explicit: a shared EC chip is not a shared register map.
No raw-register, force-model, fan-stop, or unverified quiet-mode write interface.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time


PROFILES = {
    ('ASUSTeK COMPUTER INC.', 'VC66-C2', '1602'): {
        'id': 'asus-ite8225-vc66-c2-1602',
        'bank': 0xff, 'mode': 0x2c, 'rpm_high': 0xb0, 'rpm_low': 0xb1,
    },
}
MODES = {0x00: 'normal', 0x01: 'quiet', 0xf0: 'full-speed'}
WRITABLE_MODES = {'normal': 0x00, 'full-speed': 0xf0}
DMI = Path('/sys/class/dmi/id')
MODULE = Path('/sys/module/ec_sys')
EC_IO = Path('/sys/kernel/debug/ec/ec0/io')


def select_profile(dmi=DMI):
    identity = tuple((dmi / key).read_text().strip()
                     for key in ('sys_vendor', 'board_name', 'bios_version'))
    if identity not in PROFILES:
        raise RuntimeError('No verified EC profile for vendor/board/BIOS: '
                           + repr(identity))
    return PROFILES[identity]


class Ec:
    def __init__(self, fd, profile):
        self.fd = fd
        self.profile = profile

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def byte(self, name):
        data = os.pread(self.fd, 1, self.profile[name])
        if len(data) != 1:
            raise RuntimeError('Incomplete EC read: ' + name)
        return data[0]

    def require_bank_zero(self):
        if self.byte('bank') != 0:
            raise RuntimeError('EC bank is not zero; refusing access')

    def status(self):
        # Check bank and mode on both sides; retry a torn two-byte RPM read.
        # This cannot lock out firmware. Never change the bank from userspace.
        for _ in range(5):
            self.require_bank_zero()
            mode = self.byte('mode')
            high = self.byte('rpm_high')
            low = self.byte('rpm_low')
            high_after = self.byte('rpm_high')
            mode_after = self.byte('mode')
            self.require_bank_zero()
            if high == high_after and mode == mode_after:
                rpm = (high << 8) | low
                return {'profile': self.profile['id'], 'mode': MODES.get(mode, 'unknown'),
                        'mode_raw': mode, 'fan_rpm': rpm if rpm >= 165 else 0}
        raise RuntimeError('EC values changed during every read; retry later')

    def write_mode(self, value):
        if value not in WRITABLE_MODES.values():
            raise ValueError('Only verified Normal and full-speed modes are writable')
        self.require_bank_zero()
        if os.pwrite(self.fd, bytes([value]), self.profile['mode']) != 1:
            raise RuntimeError('Incomplete EC mode write')
        self.require_bank_zero()
        if self.byte('mode') != value:
            raise RuntimeError('EC mode readback mismatch')


def emit(stage, ec):
    print(json.dumps({'stage': stage, **ec.status()}), flush=True)


@contextmanager
def exclusive_access():
    import fcntl
    # Only coordinates this tool's processes, not ACPI/firmware/other EC tools.
    fd = os.open('/run/lock/asus-ec-linux.lock',
                 os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def unload_owned_module():
    if MODULE.exists():
        (MODULE / 'parameters/write_support').write_text('N')
        subprocess.run(['modprobe', '-r', 'ec_sys'], check=True, timeout=5)


@contextmanager
def ec_session(profile, writable=False):
    already_loaded = MODULE.exists()
    if writable and already_loaded:
        raise RuntimeError('ec_sys is already loaded; refusing to alter its configuration')
    owned = not already_loaded
    device = None
    try:
        if owned:
            subprocess.run(['modprobe', 'ec_sys', 'write_support=' + ('1' if writable else '0')],
                           check=True, timeout=5)
        device = Ec(os.open(EC_IO, os.O_RDWR if writable else os.O_RDONLY), profile)
        yield device
    finally:
        if device is not None:
            device.close()
        if owned:
            unload_owned_module()


def wait_for_commit(ec, pipe, original, timeout):
    """Independent child: restore on timeout, parent exit, or missing commit."""
    ready, _, _ = select.select([pipe], [], [], timeout)
    if ready and os.read(pipe, 1) == b'D':
        return
    ec.write_mode(original)


class Watchdog:
    def __init__(self, ec, original, timeout):
        read_pipe, self.pipe = os.pipe()
        try:
            self.pid = os.fork()
        except BaseException:
            os.close(read_pipe)
            os.close(self.pipe)
            raise
        if self.pid == 0:
            os.close(self.pipe)
            code = 0
            try:
                os.setsid()
                for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
                    signal.signal(sig, signal.SIG_IGN)
                wait_for_commit(ec, read_pipe, original, timeout)
            except BaseException as error:
                print('EC watchdog restoration failed: ' + str(error), file=sys.stderr, flush=True)
                code = 1
            finally:
                os.close(read_pipe)
                os.close(ec.fd)
                try:
                    unload_owned_module()
                except BaseException as error:
                    print('EC watchdog cleanup failed: ' + str(error), file=sys.stderr, flush=True)
                    code = 1
                os._exit(code)
        os.close(read_pipe)

    def finish(self, committed):
        try:
            if committed:
                try:
                    os.write(self.pipe, b'D')
                except BrokenPipeError:
                    raise RuntimeError('EC watchdog expired; mode was not committed') from None
        finally:
            os.close(self.pipe)
            _, status = os.waitpid(self.pid, 0)
        if os.waitstatus_to_exitcode(status) != 0:
            raise RuntimeError('EC watchdog reported a restoration or cleanup failure')


@contextmanager
def ignore_cleanup_signals():
    previous = {sig: signal.signal(sig, signal.SIG_IGN)
                for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)}
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def change_mode(ec, target, seconds=None, watchdog_factory=Watchdog):
    if target not in WRITABLE_MODES.values():
        raise ValueError('Unverified target mode')
    if seconds is not None and not 1 <= seconds <= 30:
        raise ValueError('Test duration must be 1 to 30 seconds')
    original = ec.status()['mode_raw']
    # Quiet exists in firmware, but restoring it has not been runtime-validated.
    if original not in WRITABLE_MODES.values():
        raise RuntimeError('Current mode is not verified for restoration; refusing writes')
    emit('before', ec)
    with ignore_cleanup_signals():
        watchdog = watchdog_factory(ec, original, (seconds or 0) + 10)
    committed = False
    try:
        ec.write_mode(target)
        if seconds is None:
            emit('selected', ec)
        else:
            for _ in range(seconds):
                time.sleep(1)
                emit('test', ec)
            ec.write_mode(original)
            emit('restored', ec)
        committed = True
    finally:
        with ignore_cleanup_signals():
            try:
                if not committed:
                    ec.write_mode(original)
                    # Tell the child restoration succeeded, even on handled errors.
                    committed = True
            finally:
                # An open debugfs descriptor pins ec_sys. Release the parent's
                # reference before the child disables writes and unloads it.
                ec.close()
                watchdog.finish(committed)


def interrupted(signum, frame):
    raise KeyboardInterrupt('Signal ' + str(signum))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status', help='Read fan RPM and firmware mode (no EC writes)')
    setter = commands.add_parser('set-mode', help='Select a mode until firmware changes it or reboot')
    setter.add_argument('mode', choices=tuple(WRITABLE_MODES))
    test = commands.add_parser('test-full-speed', help='Temporarily disable QFan, then restore')
    test.add_argument('--seconds', type=int, choices=range(1, 31), default=10, metavar='1..30')
    args = parser.parse_args()
    if not hasattr(os, 'geteuid') or os.geteuid() != 0:
        parser.error('Run on the Linux host as root')
    for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, interrupted)
    try:
        profile = select_profile()
        with exclusive_access(), ec_session(profile, args.command != 'status') as ec:
            if args.command == 'status':
                emit('status', ec)
            elif args.command == 'set-mode':
                change_mode(ec, WRITABLE_MODES[args.mode])
            else:
                change_mode(ec, WRITABLE_MODES['full-speed'], args.seconds)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        print('asus-ec: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
