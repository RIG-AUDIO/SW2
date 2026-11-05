# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bound commands to an owned session whose leader remains reserved until cleanup.

The supervisor is not reaped until after the last group signal. Its reserved PID
prevents PGID reuse, including when the actual command has already exited.
"""
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import threading
import time

class ProcessCancelled(RuntimeError):
    def __init__(self, signum):
        self.signum=signum
        super().__init__('Command cancelled by signal '+str(signum))

class ProcessResult(int):
    def __new__(cls, value, cleanup):
        result = super().__new__(cls, value)
        result.cleanup = cleanup
        return result

def snapshot(group):
    text = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,pgid=,uid=,rss=,stat=,comm='], text=True, timeout=5)
    members=[]
    for line in text.splitlines():
        fields=line.split(None,6)
        if len(fields)!=7:continue
        pid,ppid,pgid,uid,rss=map(int,fields[:5])
        # Ninja gives each subcommand another process group in our session.
        # Include it even after its immediate parent exits. Never signal these
        # other groups by numeric PGID: their leader PID is not reserved by us.
        owned=pgid==group
        if not owned:
            try:owned=os.getsid(pid)==group
            except ProcessLookupError:continue
            except PermissionError:
                if uid==os.getuid():raise
                continue
        if owned:
            members.append(dict(zip(('pid','ppid','pgid','uid','rss_kib','state','command'),
                                    [pid,ppid,pgid,uid,rss,*fields[5:]])))
    return members

def supervise(status_fd, control_fd, argv):
    def send(value):
        try:os.write(status_fd,(json.dumps(value)+'\n').encode())
        except BrokenPipeError:lost_controller()
    def lost_controller():
        # EOF is also delivered if the controller is killed without finally.
        # This session was created by us and our own PID is still its leader.
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        os.killpg(os.getpgrp(),signal.SIGTERM)
        time.sleep(2)
        os.killpg(os.getpgrp(),signal.SIGKILL)
    send({'ready':True,'pgid':os.getpgrp(),'sid':os.getsid(0),'uid':os.getuid()})
    try:
        child=subprocess.Popen(argv,close_fds=True)
        while child.poll() is None:
            readable,_,_=select.select([control_fd],[],[],.1)
            if readable and not os.read(control_fd,1):lost_controller()
        code=child.returncode
    except OSError as error:
        code=127
        send({'launch_errno':error.errno})
    send({'exit_code':code})
    # Hold this PID/session identity until the controller finishes group cleanup.
    if not os.read(control_fd,1):lost_controller()

def run_process(argv, *, cwd, env, stdout, timeout):
    if signal.getsignal(signal.SIGCHLD)==signal.SIG_IGN:
        raise RuntimeError('Owned session cleanup requires reserving the unreaped supervisor PID')
    status_read,status_write=os.pipe();control_read,control_write=os.pipe()
    process=None;start=time.monotonic();original=125;cancelled=None
    previous_term=None
    if threading.current_thread() is threading.main_thread() and signal.getsignal(signal.SIGTERM)==signal.SIG_DFL:
        def terminated(signum, frame):raise ProcessCancelled(signum)
        previous_term=signal.signal(signal.SIGTERM,terminated)
    report={'success':False,'errors':[],'signals':[],'remaining':[],
            'timed_out':False,'cancelled':False,'peak_group_rss_kib_sampled':0,
            'peak_session_rss_kib_sampled':0,
            'peak_compiler_rss_kib_sampled':0,'ownership':'RESERVED_UNREAPED_SESSION_LEADER'}
    def observe():
        try:
            members=snapshot(process.pid)
            report['peak_group_rss_kib_sampled']=max(report['peak_group_rss_kib_sampled'],sum(m['rss_kib'] for m in members if m['pgid']==process.pid))
            report['peak_session_rss_kib_sampled']=max(report['peak_session_rss_kib_sampled'],sum(m['rss_kib'] for m in members))
            report['peak_compiler_rss_kib_sampled']=max([report['peak_compiler_rss_kib_sampled']]+[m['rss_kib'] for m in members if 'clang' in Path(m['command']).name or Path(m['command']).name in ('cc1plus','cc1')])
            return [m for m in members if m['pid']!=process.pid and not m['state'].startswith('Z')]
        except (OSError,subprocess.SubprocessError,ValueError) as error:
            report['errors'].append({'operation':'snapshot','error':type(error).__name__})
            return None
    def group_signal(sig):
        # Never poll()/wait() the supervisor before the last signal: reaping its
        # PID would invalidate the ownership proof. No arbitrary PGID is accepted.
        if process.pid==os.getpgrp():
            report['errors'].append({'operation':'ownership','error':'controller group'})
            return
        try:
            os.killpg(process.pid,sig)
            report['signals'].append(signal.Signals(sig).name)
        except ProcessLookupError:
            pass  # ESRCH is benign only if the final inventory is empty.
        except OSError as error:
            report['errors'].append({'operation':'signal','signal':int(sig),'errno':error.errno})
    try:
        process=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),
            '--supervise',str(status_write),str(control_read),'--',*map(str,argv)],
            cwd=cwd,env=env,stdout=stdout,stderr=subprocess.STDOUT,
            start_new_session=True,pass_fds=(status_write,control_read))
        os.close(status_write);status_write=None;os.close(control_read);control_read=None
        buffer=b'';ready=False;done=False;next_sample=start+1
        while not done:
            remaining=start+timeout-time.monotonic()
            if remaining<=0:
                original=124;report['timed_out']=True;break
            readable,_,_=select.select([status_read],[],[],min(remaining,1))
            if readable:
                block=os.read(status_read,65536)
                if not block:
                    report['errors'].append({'operation':'supervisor','error':'unexpected EOF'});break
                buffer+=block
                while b'\n' in buffer:
                    line,buffer=buffer.split(b'\n',1);message=json.loads(line)
                    if message.get('ready'):
                        if message!={'ready':True,'pgid':process.pid,'sid':process.pid,'uid':os.getuid()}:
                            raise RuntimeError('Owned supervisor identity mismatch')
                        ready=True
                    if 'exit_code' in message:
                        if not ready:raise RuntimeError('Missing supervisor ownership handshake')
                        original=message['exit_code'];done=True
            if time.monotonic()>=next_sample:
                observe();next_sample=time.monotonic()+1
    except BaseException as error:
        cancelled=error;report['cancelled']=True
        original=130 if isinstance(error,KeyboardInterrupt) else 128+error.signum if isinstance(error,ProcessCancelled) else 125
    finally:
        if process is not None:
            report['pgid']=process.pid
            members=observe();report['descendants_before_cleanup']=members
            # The leader remains alive even after normal command exit. Avoid
            # signals entirely when it is the only remaining session member.
            if members is None or members:
                group_signal(signal.SIGTERM)
                deadline=time.monotonic()+2
                while time.monotonic()<deadline:
                    members=observe()
                    if members==[]:break
                    time.sleep(.05)
                if members is None or members:
                    group_signal(signal.SIGKILL)
                    deadline=time.monotonic()+2
                    while time.monotonic()<deadline:
                        members=observe()
                        if members==[]:break
                        time.sleep(.05)
            report['remaining']=members
            try:os.write(control_write,b'x')
            except BrokenPipeError:pass  # Group termination may have stopped the supervisor.
            os.close(control_write);control_write=None
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                report['errors'].append({'operation':'supervisor','error':'failed to exit'})
            report['success']=members==[] and not report['errors']
        report['original_exit_code']=original;report['seconds']=round(time.monotonic()-start,3)
        for fd in (status_read,status_write,control_read,control_write):
            if fd is not None:os.close(fd)
        if getattr(stdout,'name',None) and isinstance(stdout.name,str):
            try:Path(stdout.name+'.process.json').write_text(json.dumps(report,indent=2)+'\n')
            except OSError as error:
                report['errors'].append({'operation':'write-cleanup-evidence','errno':error.errno})
                report['success']=False
        if previous_term is not None:signal.signal(signal.SIGTERM,previous_term)
    if cancelled is not None:raise cancelled
    return ProcessResult(original,report)

if __name__=='__main__':
    if len(sys.argv)<6 or sys.argv[1]!='--supervise' or sys.argv[4]!='--':
        raise SystemExit('Owned supervisor arguments required')
    supervise(int(sys.argv[2]),int(sys.argv[3]),sys.argv[5:])
