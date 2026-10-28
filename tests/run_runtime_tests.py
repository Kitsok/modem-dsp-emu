"""Focused runtime suite; excludes privileged integration and optional backends."""
import sys
import unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1]
patterns=('test_audio_monitor.py','test_dual_mode.py','test_modem_config.py','test_sip_address_selection.py','test_system_python.py',
          'test_dial_abort.py','test_modem_logging.py','test_eicon_at.py','test_logcap.py',
          'test_courier_v42.py','test_v42bis.py','test_v42_lapm.py','test_v34_mailbox.py')
suite=unittest.TestSuite(unittest.defaultTestLoader.discover(str(root/'tests'),pattern=p)
                         for p in patterns)
result=unittest.TextTestRunner().run(suite)
raise SystemExit(not result.wasSuccessful())
