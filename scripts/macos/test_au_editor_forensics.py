# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from au_editor_forensics import EditorForensics, HOST_DRIVER, crash_stack, graphics_models, host_control_source, validator_result

SOURCE = Path(__file__).resolve().parents[2]


class EditorForensicsControls(unittest.TestCase):
    def test_host_control_uses_the_existing_discovery_and_editor_lifetime(self):
        original = (SOURCE / HOST_DRIVER).read_text()
        control = host_control_source(original)
        for line in ('findAllTypesForFile', 'createPluginInstance', 'plugin.editorBeingDeleted(view)',
                     'view->addToDesktop', 'view->removeFromDesktop', 'view.reset()'):
            self.assertIn(line, control)
        self.assertIn('repeat <= 2', control)
        self.assertIn('i < 1000', control)
        self.assertIn('juce::Thread::sleep(10)', control)
        self.assertIn('parameter->setValue(random.nextFloat())', control)

    def test_second_editor_abort_cannot_pass(self):
        start = 'Starting tests in: pluginval / Editor Automation\n'
        end = 'Completed tests in pluginval / Editor Automation\n'
        failure = start + end + start + 'AppleParavirtCommandBuffer.mm, line 248\npluginval received Abort trap: 6\n'
        outcome = validator_result(9, failure)
        self.assertEqual(outcome['editor_starts'], 2)
        self.assertEqual(outcome['editor_completions'], 1)
        self.assertTrue(outcome['apple_assertion'])
        self.assertFalse(outcome['strict_au_pluginval_pass'])
        self.assertFalse(validator_result(0, start + end + 'SUCCESS\n')['strict_au_pluginval_pass'])
        self.assertTrue(validator_result(0, (start + end) * 2 + 'SUCCESS\n')['strict_au_pluginval_pass'])

    def test_crash_report_is_restricted_to_owned_executable_and_stack(self):
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / 'pluginval'
            data = {'procPath': str(executable), 'faultingThread': 0, 'secret_field': 'not captured',
                    'usedImages': [{'name': 'AppleParavirtGPU', 'path': '/unrelated/path'}],
                    'threads': [{'id': 123, 'frames': [{'imageIndex': 0, 'imageOffset': 45,
                        'symbol': '-[AppleParavirtCommandBuffer endCurrentChunk]', 'registers': 'not captured'}]}]}
            self.assertEqual(crash_stack(data, executable), {'faulting_thread': 0, 'thread_id': 123,
                'frames': [{'image': 'AppleParavirtGPU', 'imageOffset': 45,
                            'symbol': '-[AppleParavirtCommandBuffer endCurrentChunk]'}]})
            self.assertIsNone(crash_stack(data, executable.parent / 'other'))

    def test_cmake_overlay_replaces_only_native_host_driver(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            campaign = EditorForensics.__new__(EditorForensics)
            campaign.root, campaign.report = root, {}
            campaign.prepare_host_overlay()
            (root / 'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.22)\n'
                'project(SwaraXT LANGUAGES CXX)\n'
                f'add_executable(SwaraXTApplePluginHost "{SOURCE / HOST_DRIVER}")\n'
                'target_compile_options(SwaraXTApplePluginHost PRIVATE -fvisibility=hidden)\n')
            subprocess.run(['cmake','-S',root,'-B',root/'build','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
                            '-DCMAKE_PROJECT_SwaraXT_INCLUDE='+str(campaign.entry)], check=True, stdout=subprocess.DEVNULL)
            commands=json.loads((root/'build/compile_commands.json').read_text())
            self.assertEqual([Path(entry['file']).name for entry in commands],['editor-control-host.cpp'])
            self.assertIn('-fvisibility=hidden',commands[0]['command'])

    def test_graphics_report_omits_display_identifiers_and_serials(self):
        data = {'SPDisplaysDataType': [{'sppci_model': 'Virtual GPU', 'serial': 'unreported',
                    'spdisplays_ndrvs': [{'display-serial-number': 'unreported'}]}]}
        self.assertEqual(graphics_models(data), [{'sppci_model': 'Virtual GPU'}])


if __name__ == '__main__':
    unittest.main()
