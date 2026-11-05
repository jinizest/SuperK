"""Offline persistence regression tests; run directly with Python/unittest."""
import concurrent.futures
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
MODULES = [ROOT / prefix / 'device_identity.py' for prefix in (
    'src/infrastructure/external', 'addons/superk/src/infrastructure/external'
)]


def load_module(path):
    spec = importlib.util.spec_from_file_location('device_identity', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DeviceIdentityTests(unittest.TestCase):
    def test_persistence_across_clients_and_processes(self):
        for source in MODULES:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'device.json'
                with patch.dict(os.environ, {'KORAIL_DEVICE_FILE': str(path), 'KORAIL_DEVICE_ID': ''}):
                    module = load_module(source)
                    first = module.load_device_id()
                    self.assertRegex(first, r'^[0-9a-f]{16}$')
                    self.assertNotEqual(first, '558a4f02041657ea')
                    self.assertEqual(first, load_module(source).load_device_id())
                    script = ('import importlib.util,sys; '
                              's=importlib.util.spec_from_file_location("identity",sys.argv[1]); '
                              'm=importlib.util.module_from_spec(s); s.loader.exec_module(m); '
                              'print(m.load_device_id())')
                    child = subprocess.check_output([sys.executable, '-c', script, str(source)], text=True)
                    self.assertEqual(first, child.strip())
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                    path2 = Path(directory) / 'other.json'
                    with patch.dict(os.environ, {'KORAIL_DEVICE_FILE': str(path2)}):
                        self.assertNotEqual(first, module.load_device_id())

    def test_concurrent_first_use(self):
        for source in MODULES:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'device.json'
                with patch.dict(os.environ, {'KORAIL_DEVICE_FILE': str(path), 'KORAIL_DEVICE_ID': ''}):
                    module = load_module(source)
                    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
                        values = list(pool.map(lambda _: module.load_device_id(), range(32)))
                    self.assertEqual(len(set(values)), 1)
                    self.assertEqual(json.loads(path.read_text())['device_id'], values[0])
                    self.assertEqual(list(Path(directory).glob('.korail-device-*')), [])

    def test_explicit_id_and_corrupt_file(self):
        for source in MODULES:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'device.json'
                module = load_module(source)
                with patch.dict(os.environ, {'KORAIL_DEVICE_FILE': str(path), 'KORAIL_DEVICE_ID': '0123456789ABCDEF'}):
                    self.assertEqual(module.load_device_id(), '0123456789abcdef')
                    self.assertFalse(path.exists())
                    with patch.dict(os.environ, {'KORAIL_DEVICE_ID': 'invalid'}):
                        with self.assertRaises(ValueError):
                            module.load_device_id()
                    path.write_text('broken-json')
                    with patch.dict(os.environ, {'KORAIL_DEVICE_ID': ''}):
                        with self.assertRaises(ValueError):
                            module.load_device_id()
                        self.assertEqual(path.read_text(), 'broken-json')


if __name__ == '__main__':
    unittest.main()
