# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
import errno
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import shlex
import unittest
from unittest.mock import patch
from processes import run_process
from processes import ProcessCancelled, ProcessResult
from ci import Campaign
from types import SimpleNamespace

class ProcessTests(unittest.TestCase):
    def invoke(self,source,timeout=5):
        with tempfile.TemporaryDirectory() as d:
            log=Path(d)/'command.log'
            with log.open('w') as stream:
                result=run_process([sys.executable,'-c',source],cwd=d,env=os.environ.copy(),stdout=stream,timeout=timeout)
            self.assertEqual(json.loads(Path(str(log)+'.process.json').read_text())['original_exit_code'],int(result))
            return result
    def test_normal_and_nonzero_exit_do_not_signal_completed_commands(self):
        for code in (0,7):
            result=self.invoke(f'raise SystemExit({code})')
            self.assertEqual(result,code);self.assertTrue(result.cleanup['success']);self.assertEqual(result.cleanup['signals'],[])
    def test_timeout_keeps_124_and_cleans_group(self):
        result=self.invoke('import time;time.sleep(30)',timeout=.2)
        self.assertEqual(result,124);self.assertTrue(result.cleanup['success']);self.assertEqual(result.cleanup['remaining'],[])
    def test_hung_child_surviving_parent_requires_kill(self):
        source='import os,signal,time\nif os.fork()==0:\n signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)\nelse:\n time.sleep(.1)'
        result=self.invoke(source)
        self.assertEqual(result,0);self.assertTrue(result.cleanup['success']);self.assertIn('SIGKILL',result.cleanup['signals'])
    def test_esrch_is_benign_only_when_group_is_empty(self):
        with patch('processes.os.killpg',side_effect=ProcessLookupError(errno.ESRCH,'gone')) as kill:
            result=self.invoke('pass')
            kill.assert_not_called();self.assertTrue(result.cleanup['success'])
    def test_esrch_during_termination_does_not_mask_original_timeout(self):
        original=os.killpg
        def gone(group,sig):
            original(group,sig)
            raise ProcessLookupError(errno.ESRCH,'already gone')
        with patch('processes.os.killpg',side_effect=gone):
            result=self.invoke('import time;time.sleep(30)',timeout=.2)
        self.assertEqual(result,124);self.assertTrue(result.cleanup['success'])
    def test_permission_denied_is_separate_from_timeout(self):
        original=os.killpg
        def deny_term(group,sig):
            if sig==signal.SIGTERM:raise PermissionError(errno.EPERM,'denied')
            return original(group,sig)
        with patch('processes.os.killpg',side_effect=deny_term):
            result=self.invoke('import time;time.sleep(30)',timeout=.2)
        self.assertEqual(result,124);self.assertFalse(result.cleanup['success']);self.assertEqual(result.cleanup['errors'][0]['errno'],errno.EPERM)
        self.assertEqual(result.cleanup['remaining'],[])
    def test_cancellation_preserves_interrupt_and_cleans_children(self):
        previous=signal.signal(signal.SIGALRM,lambda *_:(_ for _ in ()).throw(KeyboardInterrupt()))
        try:
            with tempfile.TemporaryDirectory() as d:
                log=Path(d)/'cancel.log'
                with log.open('w') as stream:
                    signal.setitimer(signal.ITIMER_REAL,.2)
                    with self.assertRaises(KeyboardInterrupt):
                        run_process([sys.executable,'-c','import time;time.sleep(30)'],cwd=d,env=os.environ.copy(),stdout=stream,timeout=30)
                report=json.loads(Path(str(log)+'.process.json').read_text())
                self.assertTrue(report['cancelled']);self.assertTrue(report['success']);self.assertEqual(report['remaining'],[])
        finally:
            signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)
    def test_no_signal_after_supervisor_reaped(self):
        original_wait=subprocess.Popen.wait;original_kill=os.killpg;reaped=set()
        def wait(process,*args,**kwargs):
            result=original_wait(process,*args,**kwargs);reaped.add(process.pid);return result
        def kill(group,sig):
            self.assertNotIn(group,reaped);self.assertNotEqual(group,os.getpgrp());return original_kill(group,sig)
        with patch('processes.subprocess.Popen.wait',wait),patch('processes.os.killpg',kill):
            self.assertEqual(self.invoke('import time;time.sleep(30)',timeout=.2),124)
    def test_sigterm_cancellation_is_bounded_and_reported(self):
        previous=signal.signal(signal.SIGALRM,lambda *_:os.kill(os.getpid(),signal.SIGTERM))
        try:
            with tempfile.TemporaryDirectory() as d:
                log=Path(d)/'term.log'
                with log.open('w') as stream:
                    signal.setitimer(signal.ITIMER_REAL,.2)
                    with self.assertRaises(ProcessCancelled):
                        run_process([sys.executable,'-c','import time;time.sleep(30)'],cwd=d,env=os.environ.copy(),stdout=stream,timeout=30)
                report=json.loads(Path(str(log)+'.process.json').read_text())
                self.assertEqual(report['original_exit_code'],143);self.assertTrue(report['success'])
        finally:
            signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)
    def test_controller_loss_cannot_leave_live_command(self):
        with tempfile.TemporaryDirectory() as d:
            log=Path(d)/'orphan.log'
            command='import os,time;print(os.getpid(),flush=True);time.sleep(30)'
            source=f'import sys,os;sys.path.insert(0,{str(Path(__file__).parent)!r});from processes import run_process\nf=open({str(log)!r},"w");run_process([sys.executable,"-c",{command!r}],cwd={d!r},env=os.environ.copy(),stdout=f,timeout=30)'
            controller=subprocess.Popen([sys.executable,'-B','-c',source])
            deadline=time.monotonic()+5
            while time.monotonic()<deadline and not(log.exists() and log.read_text().strip()):time.sleep(.05)
            self.assertTrue(log.exists() and log.read_text().strip())
            child=int(log.read_text().strip());group=os.getpgid(child)
            controller.kill();controller.wait(timeout=3)
            deadline=time.monotonic()+5;live=True
            while time.monotonic()<deadline:
                status=subprocess.run(['ps','-p',str(child),'-o','pgid=,stat='],capture_output=True,text=True).stdout.split()
                live=bool(status) and int(status[0])==group and not status[1].startswith('Z')
                if not live:break
                time.sleep(.1)
            self.assertFalse(live,'Owned supervisor left a live command after controller loss')
    def test_cleanup_failure_cannot_erase_timeout_or_pass_campaign(self):
        with tempfile.TemporaryDirectory() as d:
            campaign=Campaign.__new__(Campaign);campaign.root=Path(d);campaign.env={};campaign.report={'commands':[]}
            result=ProcessResult(124,{'success':False,'errors':[{'errno':errno.EPERM}]})
            with patch('ci.run_process',return_value=result):
                with self.assertRaisesRegex(RuntimeError,'original exit code 124'):
                    campaign.run('build',['compiler'])
            self.assertEqual(campaign.report['commands'][0]['exit_code'],124)
            self.assertFalse(campaign.report['commands'][0]['process_cleanup']['success'])
    def test_ninja_subcommand_groups_are_observed_and_stopped(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);build=root/'build.ninja'
            build.write_text('rule wait\n  command = '+shlex.join([sys.executable,'-c','import time;time.sleep(30)'])+'\nbuild held: wait\n')
            with (root/'ninja.log').open('w') as stream:
                result=run_process(['ninja','-f',build],cwd=root,env=os.environ.copy(),stdout=stream,timeout=.5)
            self.assertEqual(result,124);self.assertTrue(result.cleanup['success'],result.cleanup)
            descendants=result.cleanup['descendants_before_cleanup']
            self.assertTrue(any(p['pgid']!=result.cleanup['pgid'] for p in descendants),descendants)
            self.assertEqual(result.cleanup['remaining'],[])
    def test_noncooperating_other_group_is_reported_not_signalled(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);release=root/'release-child';ready=root/'child-ready'
            source=f'import os,signal,time,pathlib\nif os.fork()==0:\n os.setpgid(0,0);signal.signal(signal.SIGTERM,signal.SIG_IGN)\n pathlib.Path({str(ready)!r}).write_text(str(os.getpid()))\n while not pathlib.Path({str(release)!r}).exists():time.sleep(.05)\nelse:time.sleep(30)'
            groups=[];original=os.killpg
            def signal_group(group,sig):groups.append(group);return original(group,sig)
            try:
                with (root/'different-group.log').open('w') as stream,patch('processes.os.killpg',side_effect=signal_group):
                    result=run_process([sys.executable,'-c',source],cwd=root,env=os.environ.copy(),stdout=stream,timeout=5)
                self.assertTrue(ready.exists(),'Control child did not establish its separate process group')
                self.assertEqual(result,124);self.assertFalse(result.cleanup['success'],result.cleanup)
                self.assertTrue(result.cleanup['remaining'])
                self.assertIn(int(ready.read_text()),[p['pid'] for p in result.cleanup['remaining']])
                self.assertTrue(all(p['pgid']!=result.cleanup['pgid'] for p in result.cleanup['remaining']))
                self.assertTrue(all(group==result.cleanup['pgid'] for group in groups))
            finally:
                # Cooperative release for this deliberately unkillable-by-group
                # control; never signal an unreserved foreign group to tidy tests.
                release.write_text('done')
                if 'result' in locals():
                    for child in result.cleanup['remaining']:
                        deadline=time.monotonic()+3
                        while time.monotonic()<deadline:
                            status=subprocess.run(['ps','-p',str(child['pid']),'-o','stat='],capture_output=True,text=True).stdout.strip()
                            if not status or status.startswith('Z'):break
                            time.sleep(.05)

if __name__=='__main__':unittest.main()
