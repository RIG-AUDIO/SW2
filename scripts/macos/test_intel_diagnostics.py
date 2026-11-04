# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from intel_diagnostics import DiagnosticCampaign,CANDIDATE_SHA,ARCHIVE_SHA256
class DiagnosticControls(unittest.TestCase):
    def test_crash_stays_failure_even_if_debugger_exits_zero(self):
        c=DiagnosticCampaign.__new__(DiagnosticCampaign);c.args=SimpleNamespace(profile='Release')
        with patch('ci.Campaign.run',side_effect=[-6,0]) as run:
            self.assertEqual(c.run('actual-AU',['host','AU','candidate','image'],expected=None,login=True),-6)
            self.assertEqual(run.call_count,2)
            self.assertIn('thread backtrace all',run.call_args_list[1].args[1])
    def test_wrong_candidate_origin_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            c=DiagnosticCampaign.__new__(DiagnosticCampaign);c.args=SimpleNamespace(candidate=Path(d))
            (Path(d)/'provenance.json').write_text(json.dumps({'source_sha':'0'*40}))
            with self.assertRaisesRegex(RuntimeError,'origin'):c.verified_candidate()
    def test_reference_admission_remains_pending(self):
        c=DiagnosticCampaign.__new__(DiagnosticCampaign);c.report={};c.native_reference(None,None)
        self.assertEqual(c.report['audio_reference_admission'],'REVIEW_REQUIRED')
        self.assertNotIn('FULL_NATIVE_QUALIFICATION_PASS',str(c.report))
if __name__=='__main__':unittest.main()
