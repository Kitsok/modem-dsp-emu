"""The kernel backend must not require Python site packages or MIPS imports."""
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from eicon_adsp_sip import EiconSipEndpoint


class SystemPythonTests(unittest.TestCase):
    def run_without_site(self, *args):
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        env.pop('PYTHONHOME', None)
        return subprocess.run([sys.executable, '-S', *args], cwd=ROOT,
                              env=env, text=True, capture_output=True)

    def test_sip_import_and_help_without_site_packages(self):
        code = ("import sys; sys.path.insert(0, 'tools'); "
                "import eicon_adsp_sip; "
                "assert 'unicorn' not in sys.modules; "
                "assert 'eicon_mips_shim' not in sys.modules")
        result = self.run_without_site('-c', code)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_without_site('tools/eicon_adsp_sip.py', '--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--kernel-dispatch', result.stdout)

    def test_native_mips_reports_its_optional_dependency(self):
        result = self.run_without_site('tools/eicon_adsp_sip.py', '--native-mips')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('requires the optional Unicorn Python package', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_dsp_assertions_do_not_load_the_mips_backend(self):
        endpoint = EiconSipEndpoint.__new__(EiconSipEndpoint)
        endpoint.assert_dm_clean = (0x100, 0x101, 0x261, 1)
        adsp = SimpleNamespace(adsp2181_watch_dm_writes=Mock())
        with patch('eicon_adsp_sip.ADSP', adsp), \
             patch.dict(sys.modules, {'eicon_mips_shim': None, 'unicorn': None}):
            endpoint._arm_dm_assertion(123)
        self.assertTrue(endpoint.assert_dm_armed)
        self.assertEqual(adsp.adsp2181_watch_dm_writes.call_count, 2)


if __name__ == '__main__': unittest.main()
