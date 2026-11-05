# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from intel_diagnostics import DiagnosticCampaign,ReleaseBuildProbe,CANDIDATE_SHA,ARCHIVE_SHA256
from policy import APPLE_GUARD_TEST, verify_apple_guard_test
from ci import native_test_binaries
class DiagnosticControls(unittest.TestCase):
    def test_native_test_architecture_is_verified_from_actual_binaries(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);tests=[]
            for i in range(11):
                executable=root/('test'+str(i));executable.write_bytes(b'controlled fixture')
                tests.append({'name':executable.name,'command':[str(executable)]})
            with patch('ci.subprocess.check_output',return_value='arm64\n'):
                self.assertEqual(len(native_test_binaries(root,{'tests':tests},'arm64')),11)
            with patch('ci.subprocess.check_output',return_value='x86_64\n'):
                with self.assertRaisesRegex(RuntimeError,'native architecture'):
                    native_test_binaries(root,{'tests':tests},'arm64')
            with self.assertRaisesRegex(RuntimeError,'lacks an executable'):
                native_test_binaries(root,{'tests':[{'name':'missing'}]},'arm64')
    def test_build_probe_can_never_approve_known_validator_failure(self):
        c=ReleaseBuildProbe.__new__(ReleaseBuildProbe)
        c.args=SimpleNamespace(profile='Release',optimize_build=True)
        c.report={};c.save=lambda:None;c.prepare=lambda:'JUCE'
        c.verified_candidate=lambda:[];c.configure=lambda _:('build','Release')
        calls=[];c.regressions=lambda *args:calls.append(args);c.finish_evidence=lambda:None
        with patch('intel_diagnostics.subprocess.check_output',return_value=''):c.execute()
        self.assertEqual(len(calls),1)
        self.assertEqual(c.report['full_qualification'],'BLOCKED')
        self.assertEqual(c.report['native_validation'],'NOT_RUN_IN_BUILD_PROBE')
        self.assertNotIn('NATIVE_PROFILE_PASS',c.report['decision'])
    def test_guard_test_exception_is_exact(self):
        source=Path(__file__).resolve().parents[2]
        verify_apple_guard_test(source)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/APPLE_GUARD_TEST;path.parent.mkdir(parents=True)
            path.write_text((source/APPLE_GUARD_TEST).read_text()+'\n// unexpected change\n')
            with self.assertRaisesRegex(RuntimeError,'guard-page'):verify_apple_guard_test(d)
    def test_crash_stays_failure_even_if_debugger_exits_zero(self):
        c=DiagnosticCampaign.__new__(DiagnosticCampaign);c.args=SimpleNamespace(profile='Release')
        with patch('ci.Campaign.run',side_effect=[-6,0]) as run:
            self.assertEqual(c.run('actual-AU',['host','AU','candidate','image'],expected=None,login=True),-6)
            self.assertEqual(run.call_count,2)
            self.assertIn('thread backtrace all',run.call_args_list[1].args[1])
    def test_host_visibility_covers_objective_cpp(self):
        text=(Path(__file__).resolve().parents[2]/'Tests/Apple/CMakeLists.txt').read_text()
        self.assertIn('COMPILE_LANGUAGE:CXX,OBJCXX',text)
        self.assertIn('-fvisibility=hidden;-fvisibility-inlines-hidden',text)
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
