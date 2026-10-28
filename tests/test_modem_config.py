import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from modem_config import load_config, runtime_options
import modem_service


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'modem.conf'

    def write(self, text):
        self.path.write_text(text)
        return self.path

    def test_missing_optional_file_uses_defaults_and_explicit_file_fails(self):
        values = load_config(self.path)
        self.assertEqual(values['network']['bind'], '0.0.0.0')
        with self.assertRaisesRegex(ValueError, 'does not exist'):
            load_config(self.path, required=True)

    def test_shipped_configuration_is_valid_and_idle(self):
        options, env = runtime_options(load_config(ROOT/'config/modem-emu.ini', required=True))
        self.assertNotIn('--dial', options)
        self.assertIn('--tx-v42bis', options)
        self.assertEqual(env['EICON_CODEC_MAILBOX'], '1')

    def test_file_overrides_defaults_without_interpolation(self):
        values = load_config(self.write('[network]\ndial_target=ata.example:5060\n[modem]\ncompression=none\n[logging]\nlevel=debug\n'))
        options, _ = runtime_options(values)
        self.assertNotIn('--tx-v42bis', options)
        self.assertEqual(options[options.index('--dial-target')+1], 'ata.example:5060')
        self.assertEqual(values['logging']['level'], 'debug')

    def test_rejects_unknown_fields_sections_and_default_entries(self):
        for text in ('[network]\nbnid=0.0.0.0', '[unknown]\na=1', '[DEFAULT]\na=1'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                load_config(self.write(text))

    def test_rejects_invalid_values(self):
        for section, key, value in (('network','sip_port','0'), ('network','rtp_port','65536'),
                                   ('network','bind','not-an-ip'), ('modem','compression','zip'),
                                   ('terminal','link','relative'), ('logging','level','verbose'),
                                   ('compatibility','xid_octets','5'), ('compatibility','detect','2'),
                                   ('compatibility','detect_timeout','0')):
            with self.subTest(key=key), self.assertRaises(ValueError):
                load_config(self.write(f'[{section}]\n{key}={value}\n'))

    def test_environment_is_set_before_runtime_import_and_cli_is_last(self):
        self.write('[compatibility]\ndetect=0\n')
        seen = []
        def runtime():
            seen.append((os.environ['EICON_V42_DETECT'], list(sys.argv)))
            return 0
        with patch.dict(sys.modules, {'eicon_adsp_sip':SimpleNamespace(main=runtime)}), \
             patch.dict(os.environ, {'EICON_V42_DETECT':'1'}), patch.object(sys,'argv',['modem-emu']):
            self.assertEqual(modem_service.main(['--config',str(self.path),'--log-level','debug']), 0)
        self.assertEqual(seen[0][0], '0')
        self.assertEqual(seen[0][1][-2:], ['--log-level','debug'])

    def test_check_config_does_not_import_or_start_runtime(self):
        self.write('[logging]\nlevel=info\n')
        with patch.dict(sys.modules, {'eicon_adsp_sip':None}):
            self.assertEqual(modem_service.main(['--config',str(self.path),'--check-config']), 0)

    def test_malformed_or_duplicate_configuration_is_rejected(self):
        for text in ('not ini', '[logging]\nlevel=info\nlevel=debug\n'):
            with self.assertRaises(ValueError): load_config(self.write(text))
