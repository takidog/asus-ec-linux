import importlib.util
import os
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('asus_ec', Path(__file__).parents[1] / 'tools/asus_ec.py')
ec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ec)
PROFILE = next(iter(ec.PROFILES.values()))


class FakeEc(ec.Ec):
    def __init__(self, mode=0, rpm=3250):
        super().__init__(None, PROFILE)
        self.values = {'bank': 0, 'mode': mode, 'rpm_high': rpm >> 8, 'rpm_low': rpm & 255}
        self.writes = []

    def byte(self, name):
        return self.values[name]

    def write_mode(self, value):
        self.require_bank_zero()
        self.writes.append(value)
        self.values['mode'] = value


class FakeWatchdog:
    def __init__(self, *args):
        self.finished = None

    def finish(self, committed):
        self.finished = committed


class EcTests(unittest.TestCase):
    def test_profile_rejects_unverified_board_and_bios(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for key, value in zip(('sys_vendor', 'board_name', 'bios_version'), next(iter(ec.PROFILES))):
                (root / key).write_text(value)
            self.assertEqual(ec.select_profile(root), PROFILE)
            for key, bad in (('bios_version', '1603'), ('board_name', 'MINIPC PN50'), ('sys_vendor', 'Other')):
                previous = (root / key).read_text()
                (root / key).write_text(bad)
                with self.assertRaises(RuntimeError):
                    ec.select_profile(root)
                (root / key).write_text(previous)

    def test_rpm_and_threshold_match_firmware(self):
        self.assertEqual(FakeEc(rpm=3250).status()['fan_rpm'], 3250)
        self.assertEqual(FakeEc(rpm=164).status()['fan_rpm'], 0)
        self.assertEqual(FakeEc(rpm=165).status()['fan_rpm'], 165)
        self.assertEqual(FakeEc(mode=7).status()['mode'], 'unknown')

    def test_torn_rpm_is_retried(self):
        device = FakeEc()
        reads = iter([0, 0, 12, 255, 13, 0, 0, 0, 0, 13, 0, 13, 0, 0])
        with patch.object(device, 'byte', side_effect=lambda name: next(reads)):
            self.assertEqual(device.status()['fan_rpm'], 3328)

    def test_bank_change_rejects_sample(self):
        device = FakeEc()
        reads = iter([0, 0, 12, 195, 12, 0, 1])
        with patch.object(device, 'byte', side_effect=lambda name: next(reads)):
            with self.assertRaises(RuntimeError):
                device.status()

    def test_writes_only_mode_and_checks_readback(self):
        device = FakeEc()
        def write(fd, data, offset):
            self.assertEqual(offset, 0x2c)
            self.assertEqual(data, b'\xf0')
            device.values['mode'] = data[0]
            return 1
        with patch.object(ec.os, 'pwrite', side_effect=write, create=True):
            ec.Ec.write_mode(device, 0xf0)
        device.values['bank'] = 1
        with patch.object(ec.os, 'pwrite', create=True) as writer:
            with self.assertRaises(RuntimeError):
                ec.Ec.write_mode(device, 0)
            writer.assert_not_called()
        with self.assertRaises(ValueError):
            ec.Ec.write_mode(device, 1)

    def test_write_readback_mismatch_fails(self):
        with patch.object(ec.os, 'pwrite', return_value=1, create=True):
            with self.assertRaises(RuntimeError):
                ec.Ec.write_mode(FakeEc(), 0xf0)

    @unittest.skipUnless(hasattr(signal, 'SIGHUP'), 'POSIX signal handling')
    def test_temporary_change_restores_on_success_and_exception(self):
        for failure in (None, RuntimeError('sensor disappeared'), KeyboardInterrupt()):
            with self.subTest(failure=failure):
                device = FakeEc()
                watchdog = FakeWatchdog()
                with patch.object(ec, 'emit'), patch.object(ec.time, 'sleep', side_effect=failure):
                    if failure is None:
                        ec.change_mode(device, 0xf0, 1, lambda *args: watchdog)
                    else:
                        with self.assertRaises(type(failure)):
                            ec.change_mode(device, 0xf0, 1, lambda *args: watchdog)
                self.assertEqual(device.writes, [0xf0, 0])
                self.assertTrue(watchdog.finished)

    @unittest.skipUnless(hasattr(signal, 'SIGHUP'), 'POSIX signal handling')
    def test_selected_mode_is_committed(self):
        device = FakeEc()
        watchdog = FakeWatchdog()
        with patch.object(ec, 'emit'):
            ec.change_mode(device, 0xf0, watchdog_factory=lambda *args: watchdog)
        self.assertEqual(device.writes, [0xf0])
        self.assertTrue(watchdog.finished)

    def test_unverified_original_mode_cannot_be_written(self):
        device = FakeEc(mode=1)
        with self.assertRaises(RuntimeError):
            ec.change_mode(device, 0xf0, 1)
        self.assertEqual(device.writes, [])

    def test_existing_module_is_not_reconfigured_for_writes(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(ec, 'MODULE', Path(directory)):
            with patch.object(ec.subprocess, 'run') as run:
                with self.assertRaises(RuntimeError):
                    with ec.ec_session(PROFILE, writable=True):
                        self.fail('Must not open EC')
                run.assert_not_called()

    @unittest.skipUnless(hasattr(signal, 'SIGHUP'), 'POSIX signal handling')
    def test_parent_closes_ec_before_watchdog_unloads_module(self):
        device = FakeEc()
        with tempfile.TemporaryFile() as descriptor:
            device.fd = os.dup(descriptor.fileno())
            fd = device.fd
            test_case = self
            class CheckClose(FakeWatchdog):
                def finish(self, committed):
                    test_case.assertIsNone(device.fd)
                    with test_case.assertRaises(OSError):
                        os.fstat(fd)
                    super().finish(committed)
            with patch.object(ec, 'emit'):
                ec.change_mode(device, 0xf0, watchdog_factory=CheckClose)


@unittest.skipUnless(hasattr(os, 'fork'), 'Linux/POSIX watchdog integration')
class WatchdogTests(unittest.TestCase):
    def run_guard(self, payload, timeout=1):
        # Real independent process and pipe; synthetic EC file, no hardware.
        with tempfile.TemporaryFile() as hardware:
            hardware.write(bytes(256))
            hardware.flush()
            os.pwrite(hardware.fileno(), b'\xf0', 0x2c)
            read_pipe, write_pipe = os.pipe()
            pid = os.fork()
            if pid == 0:
                os.close(write_pipe)
                try:
                    ec.wait_for_commit(ec.Ec(hardware.fileno(), PROFILE), read_pipe, 0, timeout)
                except BaseException:
                    os._exit(1)
                os._exit(0)
            try:
                if payload is not None:
                    if payload:
                        os.write(write_pipe, payload)
                    os.close(write_pipe)
                    write_pipe = None
                _, status = os.waitpid(pid, 0)
                self.assertEqual(os.waitstatus_to_exitcode(status), 0)
                return os.pread(hardware.fileno(), 1, 0x2c)
            finally:
                os.close(read_pipe)
                if write_pipe is not None:
                    os.close(write_pipe)

    def test_parent_disconnect_restores(self):
        self.assertEqual(self.run_guard(b''), b'\x00')

    def test_timeout_restores_even_with_live_parent(self):
        self.assertEqual(self.run_guard(None, 0.05), b'\x00')

    def test_commit_preserves_selected_mode(self):
        self.assertEqual(self.run_guard(b'D'), b'\xf0')


if __name__ == '__main__':
    unittest.main()
