import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('fan_cache', Path(__file__).parents[1] / 'pve/fan-cache.py')
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


class CacheTests(unittest.TestCase):
    def test_publish_replaces_complete_snapshot_and_keeps_no_temp_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache.publish({'fan_rpm': 3247, 'mode': 'normal'}, root)
            first = json.loads((root / 'status.json').read_text())
            cache.publish({'fan_rpm': 5300, 'mode': 'full-speed'}, root)
            second = json.loads((root / 'status.json').read_text())
            self.assertEqual(first['mode'], 'normal')
            self.assertEqual(second['fan_rpm'], 5300)
            self.assertGreaterEqual(second['updated_at'], first['updated_at'])
            self.assertEqual([p.name for p in root.iterdir()], ['status.json'])

    def test_failed_publish_preserves_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache.publish({'mode': 'normal'}, root)
            with patch.object(cache.os, 'replace', side_effect=OSError('full filesystem')):
                with self.assertRaises(OSError):
                    cache.publish({'mode': 'full-speed'}, root)
            self.assertEqual(json.loads((root / 'status.json').read_text())['mode'], 'normal')
            self.assertEqual([p.name for p in root.iterdir()], ['status.json'])


    @unittest.skipUnless(os.name == 'posix', 'POSIX signal cleanup')
    def test_sample_deadline_allows_child_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'cleanup'
            script = """import signal,time,sys
from pathlib import Path
def stop(*args):
    Path(sys.argv[1]).write_text('cleaned')
    sys.exit(0)
signal.signal(signal.SIGTERM,stop)
time.sleep(60)
"""
            code, _, expired = cache.run_sample([sys.executable, '-c', script, str(marker)], timeout=0.3)
            self.assertTrue(expired)
            self.assertEqual(code, 0)
            self.assertEqual(marker.read_text(), 'cleaned')

    @unittest.skipUnless(os.name == 'posix', 'POSIX signal cleanup')
    def test_unresponsive_sample_is_killed_and_reaped(self):
        script = 'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)'
        code, _, expired = cache.run_sample([sys.executable,'-c',script],timeout=0.3,grace=0.1)
        self.assertTrue(expired)
        self.assertLess(code, 0)


if __name__ == '__main__':
    unittest.main()
