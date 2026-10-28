"""The DSP and LAPM roles must follow each call, not the previous call."""
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from eicon_adsp_sip import EiconSipEndpoint, Call
from eicon_at import AtParser, ActionKind
from modem_config import load_config

SDP='v=0\r\nc=IN IP4 127.0.0.1\r\nm=audio 4000 RTP/AVP 0\r\na=rtpmap:0 PCMU/8000\r\n'


class DualModeTests(unittest.TestCase):
    def endpoint(self):
        ep=EiconSipEndpoint.__new__(EiconSipEndpoint)
        ep.modem_role='auto';ep.preboot_card=None;ep.native_mips=False
        ep.kernel_dispatch=True;ep.law='pcmu';ep.analog_codec_rate=9600
        ep.db_words={};ep.assert_dm_clean=None;ep._arm_watches=Mock()
        ep.call=None;ep.outgoing=None;ep.pending_invite=None;ep.cancelled_outgoing={}
        ep.at=AtParser();ep.pty=Mock();ep.verbose=False;ep.ring_seconds=2
        ep.payload_type=0;ep.bind='0.0.0.0';ep.advertised='127.0.0.1';ep.sip_port=5072
        ep.codec_name='PCMU';ep.response=Mock();ep.at_apply_options=Mock()
        return ep

    def test_auto_and_fixed_roles(self):
        ep=self.endpoint()
        for mode, expected in (('auto',('calling','answer')),('calling',('calling','calling')),('answer',('answer','answer'))):
            ep.modem_role=mode
            self.assertEqual((ep.role_for(outgoing=True),ep.role_for(outgoing=False)),expected)

    def test_default_configuration_selects_auto(self):
        self.assertEqual(load_config(Path('/nonexistent-config'))['modem']['role'],'auto')

    def test_builds_each_dsp_with_resolved_role(self):
        ep=self.endpoint()
        for role in ('calling','answer','calling'):
            card=SimpleNamespace(firmware_set='analog109',cpu=1,boot=Mock(),configure_modem=Mock())
            with patch('eicon_adsp_sip.dsp_drive.FIRMWARE_SET','analog109'), \
                 patch('analog_kernel_dispatch.AnalogKernelModem',return_value=card) as factory:
                self.assertIs(ep.build_card(role),card)
            factory.assert_called_once_with(modem_role=role,law='pcmu',codec_rate=9600)
            card.configure_modem.assert_called_once_with(role,'pcmu')
            self.assertEqual(card._sip_modem_role,role)

    def test_preboot_cache_is_reused_only_for_the_matching_role(self):
        ep=self.endpoint();cached=SimpleNamespace(_sip_modem_role='answer');ep.preboot_card=cached
        fresh=SimpleNamespace(firmware_set='analog109',cpu=1,boot=Mock(),configure_modem=Mock())
        with patch('eicon_adsp_sip.dsp_drive.FIRMWARE_SET','analog109'), \
             patch('analog_kernel_dispatch.AnalogKernelModem',return_value=fresh):
            self.assertIs(ep.build_card('calling'),fresh)
        self.assertIs(ep.preboot_card,cached)
        self.assertIs(ep.build_card('answer'),cached)
        self.assertIsNone(ep.preboot_card)

    def test_lapm_role_is_taken_from_the_call(self):
        ep=self.endpoint();ep.tx_v42=True;ep.tx_v42bis=True;ep.tx_v44=False;ep.ppp_config=None
        for role, expected in (('calling','originator'),('answer','answerer')):
            card=SimpleNamespace(lapm=None,pm={})
            call=Call(None,None,'id','tag',card,modem_role=role)
            with patch('v34_mailbox.claim_tx_mailbox'),patch('v34_mailbox.claim_wide_rx_mailbox'),patch('v34_mailbox.V34Mailbox'):
                ep._attach_reactive_engine(call)
            self.assertEqual(card.lapm.role,expected)

    def test_incoming_answer_builds_answer_role(self):
        ep=self.endpoint();card=object()
        ep.pending_invite=dict(headers={'from':'<sip:caller@peer>','to':'<sip:eicon@local>'},peer=('127.0.0.1',5060),media=('127.0.0.1',4000),call_id='incoming')
        ep.build_card=Mock(return_value=card);ep._attach_reactive_engine=Mock();ep.attach_physical_line=Mock();ep.local_sdp=Mock(return_value=SDP)
        ep._complete_answer()
        ep.build_card.assert_called_once_with('answer')
        self.assertEqual(ep.call.modem_role,'answer')
        self.assertEqual(ep.response.call_args.args[0],200)

    def test_outgoing_answer_keeps_the_calling_role(self):
        ep=self.endpoint();ep.outgoing=dict(peer=('127.0.0.1',5060),call_id='outgoing',tag='local',modem_role='calling')
        ep.dialed_card=object();ep.send_ack=Mock();ep._attach_reactive_engine=Mock();ep.attach_physical_line=Mock()
        ep.on_invite_response(200,{'call-id':'outgoing','to':'<sip:peer>'},SDP,('127.0.0.1',5060))
        self.assertEqual(ep.call.modem_role,'calling')

    def incoming(self,ep):
        data=('INVITE sip:eicon@local SIP/2.0\r\nCall-ID: incoming\r\nFrom: <sip:caller@peer>\r\n\r\n'+SDP).encode()
        ep.sip=SimpleNamespace(recvfrom=Mock(return_value=(data,('127.0.0.1',5060))))
        ep.on_sip()

    def test_autoanswer_waits_for_cadence_without_spurious_no_carrier(self):
        ep=self.endpoint();ep.at.registers[0]=1
        self.incoming(ep)
        self.assertGreater(ep.pending_invite['answer_at'],time.monotonic())
        ep.pty.write_terminal.assert_called_once_with(b'\r\nRING\r\n')
        self.assertFalse(ep.at.actions)

    def test_manual_answer_waits_for_ata_without_early_ok(self):
        ep=self.endpoint();ep.at.registers[0]=0
        self.incoming(ep)
        self.assertIsNone(ep.pending_invite['answer_at'])
        self.assertEqual(ep.at.execute(b'ATA'),b'')
        ep._complete_answer=Mock()
        self.assertEqual(ep.on_at_action(ep.at.actions.pop()),b'')
        ep._complete_answer.assert_called_once()

    def test_incoming_call_is_busy_during_outgoing_dial(self):
        ep=self.endpoint();ep.outgoing={'call_id':'outgoing'}
        self.incoming(ep)
        self.assertEqual(ep.response.call_args.args[0],486)
        self.assertIsNone(ep.pending_invite)

    def test_ata_without_a_call_returns_no_carrier_and_resets_pending_state(self):
        ep=self.endpoint()
        self.assertEqual(ep.at.execute(b'ATA'),b'')
        self.assertEqual(ep.on_at_action(ep.at.actions.pop()),b'\r\nNO CARRIER\r\n')
        self.assertFalse(ep.at.dial_pending)

    def test_keypress_during_manual_answer_aborts_setup(self):
        parser=AtParser()
        reply,_=parser.feed(b'ATA\r\n')
        self.assertNotIn(b'OK',reply)
        self.assertTrue(parser.dial_pending)
        parser.feed(b'x')
        self.assertEqual(parser.actions[-1].kind,ActionKind.ABORT_DIAL)

    def test_hangup_rejects_a_ringing_call(self):
        ep=self.endpoint();ep.at.registers[0]=0
        self.incoming(ep)
        ep.at.execute(b'ATH')
        ep.on_at_action(ep.at.actions.pop())
        self.assertEqual(ep.response.call_args.args[0],486)
        self.assertIsNone(ep.pending_invite)

    def test_dial_does_not_displace_a_ringing_incoming_call(self):
        ep=self.endpoint();ep.pending_invite={'call_id':'incoming'}
        self.assertFalse(ep.dial('100','127.0.0.1:5060'))
        self.assertEqual(ep.pending_invite['call_id'],'incoming')
