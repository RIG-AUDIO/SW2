#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
"""One original AU validator invocation with bounded editor controls on abort."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time

from ci import SOURCE, digest
from infrastructure import AU_PATH, cleanup_au
from intel_diagnostics import DiagnosticCampaign, ARCHIVE_SHA256
from parity_probe import once
from policy import hosted_root, owned_path, require, safe_extract_tar

BASELINE = 'de3680a11ba341a0d5fe13524d1c4ccdc2a7fb6f'
HOST = 'SwaraXTApplePluginHost'
HOST_DRIVER = 'Tests/Apple/PluginHost.cpp'
DISPLAY_FIELDS = ('sppci_model', 'sppci_vendor', 'sppci_device_type', 'spdisplays_metal',
                  'spdisplays_metal_family', 'spdisplays_vram', 'spdisplays_vram_shared')


def graphics_models(data):
    return [{key: item[key] for key in DISPLAY_FIELDS if isinstance(item.get(key), str)}
            for item in data.get('SPDisplaysDataType', [])]


def crash_stack(data, executable):
    """Admit only frame evidence for this job's executable, never a raw report."""
    if not isinstance(data, dict) or not isinstance(data.get('procPath'), str) or Path(data['procPath']).resolve() != executable.resolve():
        return None
    index = data.get('faultingThread')
    threads = data.get('threads', [])
    if not isinstance(threads, list) or type(index) is not int or index < 0 or index >= len(threads):
        return None
    thread = threads[index]
    images = data.get('usedImages', [])
    frames = []
    for frame in thread.get('frames', [])[:48]:
        entry = {}
        i = frame.get('imageIndex')
        if type(i) is int and 0 <= i < len(images):
            name = images[i].get('name', '')
            if isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9_. +()-]{1,120}', name):
                entry['image'] = name
        for key in ('imageOffset', 'symbolLocation'):
            if type(frame.get(key)) is int:
                entry[key] = frame[key]
        symbol = frame.get('symbol')
        if isinstance(symbol, str) and re.fullmatch(r'[A-Za-z0-9_:$ .+\[\]()<>*,&~=-]{1,240}', symbol):
            entry['symbol'] = symbol
        if entry:
            frames.append(entry)
    return {'faulting_thread': index, 'thread_id': thread.get('id') if type(thread.get('id')) is int else None,
            'frames': frames}


def collect_crash_stacks(executable, since):
    directory = Path.home() / 'Library/Logs/DiagnosticReports'
    if not directory.is_dir() or directory.is_symlink():
        return []
    stacks = []
    for path in sorted(directory.glob(executable.name + '-*.ips')):
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_mtime < since or path.stat().st_size > 16 * 1024 * 1024:
                continue
            content = path.read_text()
            # macOS .ips begins with a one-line metadata object.
            data = json.loads(content.split('\n', 1)[1])
            stack = crash_stack(data, executable)
            if stack is not None:
                stacks.append(stack)
        except (OSError, IndexError, ValueError):
            continue
    return stacks


def host_control_source(text):
    """Reuse actual host discovery and lifetime handling in a build-owned copy."""
    text = '#include <atomic>\n#include <thread>\n' + text
    text = once(text, 'const juce::File& screenshot)', 'const juce::File& screenshot, bool automate = false)')
    text = once(text, '    const auto closeEditor =', '    std::puts("EDITOR_STAGE create");\n    const auto closeEditor =')
    text = once(text, '    pump(400);', '''    std::puts("EDITOR_STAGE peer-visible");
    pump(400);
    std::puts("EDITOR_STAGE initial-message-pump-complete");
    if (automate)
    {
        // Match the validator's update count, cadence and background-thread
        // parameter setter. The control has its own fixed random stream.
        std::atomic<bool> done{false};
        std::puts("EDITOR_STAGE automation-start");
        std::thread automation([&]
        {
            juce::Random random(0x53776172);
            for (int i = 0; i < 1000; ++i)
            {
                for (auto* parameter : plugin.getParameters())
                    parameter->setValue(random.nextFloat());
                if ((i + 1) % 250 == 0)
                    std::printf("EDITOR_AUTOMATION completed=%d\\n", i + 1);
                juce::Thread::sleep(10);
            }
            done.store(true, std::memory_order_release);
        });
        while (!done.load(std::memory_order_acquire))
        {
            view->repaint();
            pump(20);
        }
        automation.join();
        std::puts("EDITOR_STAGE automation-complete");
    }''')
    text = once(text, '    view->setVisible(false);', '    std::puts("EDITOR_STAGE closing");\n    view->setVisible(false);')
    text = once(text, '    view.reset();', '    view.reset();\n    std::puts("EDITOR_STAGE destroyed");')
    text = once(text, '    try\n    {', '    std::setvbuf(stdout, nullptr, _IONBF, 0);\n    try\n    {')
    text = once(text, '        auto second = manager.createPluginInstance', '''        if (juce::String(argv[3]) == "--editor-automation-control")
        {
            require(first->getParameters().size() > 0, "control exposes parameters");
            first->prepareToPlay(48000.0, 256);
            for (int repeat = 1; repeat <= 2; ++repeat)
            {
                std::printf("EDITOR_CONTROL repeat=%d\\n", repeat);
                editor(*first, {}, true);
                pump(200);
                std::puts("EDITOR_STAGE post-close-message-pump-complete");
            }
            first->releaseResources();
            first.reset();
            pump(200);
            std::puts("EDITOR_AUTOMATION_CONTROL_PASS");
            return 0;
        }
        auto second = manager.createPluginInstance''')
    return text


def validator_result(code, log):
    starts = log.count('Starting tests in: pluginval / Editor Automation')
    completions = log.count('Completed tests in pluginval / Editor Automation')
    return {'exit_code': int(code),
            'editor_starts': starts, 'editor_completions': completions,
            'apple_assertion': 'AppleParavirtCommandBuffer.mm, line 248' in log,
            'abort_signal_reported': 'Abort trap: 6' in log,
            'strict_au_pluginval_pass': code == 0 and starts == completions == 2 and
                'SUCCESS' in log.splitlines() and 'Abort trap:' not in log}


class EditorForensics(DiagnosticCampaign):
    def run(self, name, argv, **kwargs):
        if name == 'configure':
            argv = [*argv, '-DCMAKE_PROJECT_SwaraXT_INCLUDE=' + str(self.entry)]
        return super().run(name, argv, **kwargs)

    def prepare_host_overlay(self):
        original = SOURCE / HOST_DRIVER
        expected = subprocess.check_output(['git', 'show', BASELINE + ':' + HOST_DRIVER], cwd=SOURCE, text=True)
        require(original.read_text() == expected, 'Native host changed from reviewed baseline')
        driver = self.root / 'editor-control-host.cpp'
        driver.write_text(host_control_source(expected))
        install = self.root / 'install-editor-control.cmake'
        install.write_text(f'''get_target_property(sources {HOST} SOURCES)
list(LENGTH sources before)
list(FILTER sources EXCLUDE REGEX "(^|/)PluginHost.cpp$")
list(LENGTH sources after)
math(EXPR removed "${{before}}-${{after}}")
if(NOT removed EQUAL 1)
  message(FATAL_ERROR "Expected exactly one native host source")
endif()
set_property(TARGET {HOST} PROPERTY SOURCES "${{sources}}")
target_sources({HOST} PRIVATE "{driver.as_posix()}")
''')
        self.entry = self.root / 'editor-control-entry.cmake'
        self.entry.write_text(f'cmake_language(DEFER CALL include "{install.as_posix()}")\n')
        self.report['control_driver_sha256'] = digest(driver)

    def execute(self):
        self.report.update(diagnostic_only=True, full_qualification='BLOCKED',
                           audio_reference_admission='REVIEW_REQUIRED', known_good_au_control='NOT_RUN',
                           physical_mac_control='NOT_RUN', root_cause='UNRESOLVED', failure_reproduced='NOT_RUN')
        try:
            juce = self.prepare()
            require(not subprocess.check_output(['git', 'diff', '--name-only', BASELINE, 'HEAD', '--',
                    'Source', 'Tests', 'resources', 'third_party'], cwd=SOURCE, text=True).strip(), 'Reviewed product or tests changed')
            try:
                display = subprocess.check_output(['/usr/sbin/system_profiler', 'SPDisplaysDataType', '-json'], text=True, timeout=60)
                self.report['graphics'] = graphics_models(json.loads(display))
            except (OSError, subprocess.SubprocessError, ValueError) as error:
                self.report['graphics_probe_error'] = type(error).__name__
            self.report['macos_build'] = subprocess.check_output(['sw_vers', '-buildVersion'], text=True).strip()
            au, vst = self.verified_candidate()
            manifest = json.loads((self.args.candidate / 'provenance.json').read_text())
            self.report['candidate_binaries'] = manifest['binaries']
            self.prepare_host_overlay()
            build, config = self.configure(juce)
            self.run('build-editor-control-host', ['cmake', '--build', build, '--parallel', '2', '--target', HOST])
            host = build / 'Tests/Apple' / (HOST + '_artefacts') / config / HOST
            self.verify_native_host(host)
            self.report['control_host_sha256'] = digest(host)
            code = None
            try:
                self.register_ci_au(au, host)
                began = time.time()
                code = self.external_validation(AU_PATH, 'AU')
                log = (self.root / 'pluginval-AU.log').read_text(errors='replace')
                result = validator_result(code, log)
                self.report['validator_result'] = result
                reproduced = result['apple_assertion'] and result['abort_signal_reported'] and code != 0
                self.report['failure_reproduced'] = 'YES' if reproduced else 'NO'
                self.save()
                if reproduced:
                    self.editor_control(host, 'AU', AU_PATH)
            finally:
                cleanup_au(self.root, self.run)
            if self.report['failure_reproduced'] == 'YES':
                self.editor_control(host, 'VST3', vst)
            self.report['validator_crash_stacks'] = collect_crash_stacks(self.root / 'pluginval-tool/pluginval.app/Contents/MacOS/pluginval', began)
            self.report['decision'] = 'FOCUSED_AU_EDITOR_EVIDENCE_COMPLETE'
            self.finish_evidence()
            require(self.report['validator_result']['strict_au_pluginval_pass'], 'Original AU pluginval did not pass, exit '+str(code))
        except BaseException as error:
            self.report['decision'] = ('FOCUSED_AU_VALIDATION_FAILED' if 'validator_result' in self.report
                                       else 'FOCUSED_AU_EDITOR_EVIDENCE_INCOMPLETE')
            self.report['failure'] = str(error)
            raise
        finally:
            self.save()

    def editor_control(self, host, fmt, bundle):
        began = time.time()
        name = 'editor-control-' + fmt
        code = self.run(name, [host, fmt, bundle, '--editor-automation-control'], expected=None, timeout=180, login=True)
        log = (self.root / (name + '.log')).read_text(errors='replace')
        passed = code == 0 and 'EDITOR_AUTOMATION_CONTROL_PASS' in log and log.count('EDITOR_STAGE destroyed') == 2 and not any(
            term in log for term in ('FAIL:', 'Assertion failed', 'JUCE Assertion failure', 'Sanitizer:'))
        self.report.setdefault('editor_controls', {})[fmt] = {'exit_code': int(code), 'pass': passed,
            'crash_stacks': collect_crash_stacks(host, began)}
        self.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arch', choices=['x86_64'], required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--candidate-download', type=Path, required=True)
    args = parser.parse_args()
    hosted_root(args.root, SOURCE)
    archive = owned_path(args.candidate_download, os.environ['RUNNER_TEMP']) / 'swaraxt-unsigned-universal.tar.gz'
    require(archive.is_file() and not archive.is_symlink() and digest(archive) == ARCHIVE_SHA256, 'Pinned candidate archive mismatch')
    extraction = owned_path(Path(os.environ['RUNNER_TEMP']) / 'au-editor-candidate', os.environ['RUNNER_TEMP'])
    safe_extract_tar(archive, extraction)
    args.candidate = extraction / 'unsigned-universal'
    args.candidate_archive_sha256 = ARCHIVE_SHA256
    args.profile, args.task, args.mode = 'Release', 'au-editor-forensics', 'diagnostic'
    args.source_sha = os.environ['GITHUB_SHA']
    args.base_source_sha = '5e7b967db0b52f773f382217a72c6c0c3ff6b8f7'
    EditorForensics(args).execute()


if __name__ == '__main__':
    main()
