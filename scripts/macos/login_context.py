# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded owned validation agents in an ephemeral macOS GUI login domain."""
import json
import os
from pathlib import Path
import plistlib
import signal
import subprocess
import sys
import time
import uuid

from policy import hosted_root, owned_path, require, run_process, ProcessResult


def worker(folder):
    folder = Path(folder).resolve()
    config = json.loads((folder / 'command.json').read_text())
    def cancelled(signum, frame):
        raise RuntimeError('Owned worker cancelled')
    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    try:
        with Path(config['log']).open('x') as log:
            code = run_process(config['command'], cwd=config['cwd'], env=config['environment'],
                               stdout=log, timeout=config['timeout'])
    except Exception:
        code = 125
    partial = folder / 'result.partial'
    partial.write_text(json.dumps({'exit_code': code, 'process_cleanup':getattr(code,'cleanup',None)}))
    partial.replace(folder / 'result.json')


def run_login(command, logfile, root, timeout, env):
    root = hosted_root(root)
    logfile = owned_path(logfile, root)
    require(not logfile.exists(), 'Owned login log already exists')
    domain = 'gui/' + str(os.getuid())
    subprocess.run(['/bin/launchctl', 'print', domain], check=True, capture_output=True, timeout=30)
    folder = root / ('owned-login-' + logfile.stem)
    folder.mkdir(mode=0o700)
    allowed = ('PATH', 'HOME', 'USER', 'LOGNAME', 'TMPDIR', 'GITHUB_ACTIONS', 'RUNNER_TEMP',
               'CFFIXED_USER_HOME', 'ASAN_OPTIONS', 'UBSAN_OPTIONS', 'TSAN_OPTIONS')
    environment = {key: value for key, value in env.items() if key in allowed or key.startswith('SWARAXT_')}
    config = {'command': list(map(str, command)), 'cwd': str(root), 'log': str(logfile),
              'environment': environment, 'timeout': timeout}
    (folder / 'command.json').write_text(json.dumps(config))
    label = 'com.montronedsp.swaraxt.ci.' + uuid.uuid4().hex
    agent = folder / 'owned-agent.plist'
    agent.write_bytes(plistlib.dumps({'Label': label,
        'ProgramArguments': [sys.executable, '-B', str(Path(__file__).resolve()), '--worker', str(folder)],
        'RunAtLoad': True, 'ProcessType': 'Background', 'WorkingDirectory': str(folder),
        'StandardOutPath': str(folder / 'worker-stdout.log'),
        'StandardErrorPath': str(folder / 'worker-stderr.log')}))
    registered = False
    try:
        result = subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(agent)], capture_output=True, timeout=30)
        require(result.returncode == 0, 'Owned login-session validation agent could not start')
        registered = True
        deadline = time.monotonic() + timeout + 30
        while time.monotonic() < deadline:
            result_file = folder / 'result.json'
            if result_file.exists():
                result = json.loads(result_file.read_text())
                return ProcessResult(result['exit_code'], result['process_cleanup']) if result.get('process_cleanup') is not None else result['exit_code']
            time.sleep(1)
        return 124
    finally:
        if registered:
            cleanup = subprocess.run(['/bin/launchctl', 'bootout', domain + '/' + label], capture_output=True, timeout=30).returncode
            (folder / 'cleanup.json').write_text(json.dumps({'exit_code': cleanup, 'desktop_control': False}))
            require(cleanup == 0, 'Owned login-session agent cleanup failed')


if __name__ == '__main__':
    require(len(sys.argv) == 3 and sys.argv[1] == '--worker', 'Owned worker arguments required')
    worker(sys.argv[2])
