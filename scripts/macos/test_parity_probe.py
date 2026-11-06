# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from parity_probe import overlay, DRIVERS, capture_driver, REQUIRED_TESTS, required_commands
from parity_metrics import compare, q20
from policy import verify_dual_reference_selection, DUAL_REFERENCE_TEST

SOURCE=Path(__file__).resolve().parents[2]

class ParityControls(unittest.TestCase):
    def inventory(self):
        return {'tests':[{'name':name,'command':['/build/'+name,'argument']} for name in REQUIRED_TESTS]}

    def test_unrelated_entries_without_command_are_not_extracted(self):
        listing=self.inventory()
        listing['tests'].insert(0,{'name':'UnbuiltUnrelatedTest'})
        self.assertEqual(set(required_commands(listing)),set(REQUIRED_TESTS))

    def test_missing_required_target_is_rejected(self):
        listing=self.inventory();listing['tests'].pop()
        with self.assertRaisesRegex(RuntimeError,'Missing required parity targets: '+REQUIRED_TESTS[-1]):
            required_commands(listing)

    def test_required_target_without_command_is_rejected(self):
        for command in (None,[],[''],[None],'executable'):
            listing=self.inventory();listing['tests'][0]['command']=command
            with self.assertRaisesRegex(RuntimeError,'lacks an executable command: '+REQUIRED_TESTS[0]):
                required_commands(listing)
        listing=self.inventory();del listing['tests'][0]['command']
        with self.assertRaisesRegex(RuntimeError,'lacks an executable command'):
            required_commands(listing)

    def test_valid_target_commands_preserve_arguments(self):
        listing=self.inventory()
        self.assertEqual(required_commands(listing),{t['name']:t['command'] for t in listing['tests']})

    def test_duplicate_required_target_is_rejected(self):
        listing=self.inventory();listing['tests'].append(listing['tests'][0])
        with self.assertRaisesRegex(RuntimeError,'Duplicate required parity target'):
            required_commands(listing)

    def test_reference_selection_platform_matrix(self):
        text=(SOURCE/DUAL_REFERENCE_TEST).read_text().split('// SWARAXT_DUAL_PLATFORM_GOLDENS_BEGIN\n')[1].split('// SWARAXT_DUAL_PLATFORM_GOLDENS_END')[0]
        text=text.replace('#include "DualSvfCurrentLinuxGoldens.h"','CURRENT').replace('#include "DualSvfSection2Goldens.h"','HISTORICAL')
        compiler=shutil.which('c++')
        self.assertIsNotNone(compiler)
        for macros,expected in ((['__linux__'],'CURRENT'),(['_MSC_VER'],'CURRENT'),
            (['__APPLE__','__x86_64__'],'CURRENT'),(['__APPLE__','__aarch64__'],'CURRENT'),([], 'HISTORICAL')):
            actual=subprocess.check_output([compiler,'-E','-P','-undef','-x','c++',*['-D'+v for v in macros],'-'],input=text,text=True).strip()
            self.assertEqual(actual,expected,macros)

    def test_selector_exception_rejects_other_edits(self):
        verify_dual_reference_selection(SOURCE)
        original=subprocess.check_output(['git','show','5e7b967db0b52f773f382217a72c6c0c3ff6b8f7:'+DUAL_REFERENCE_TEST],cwd=SOURCE,text=True)
        with tempfile.TemporaryDirectory() as d:
            file=Path(d)/DUAL_REFERENCE_TEST;file.parent.mkdir(parents=True)
            file.write_text((SOURCE/DUAL_REFERENCE_TEST).read_text()+'\n// not approved\n')
            with patch('policy.subprocess.check_output',return_value=original):
                with self.assertRaisesRegex(RuntimeError,'Unreviewed Dual'):verify_dual_reference_selection(d)

    def test_overlay_retains_all_assertions_and_rejects_anchor_drift(self):
        for relative in DRIVERS.values():
            original=(SOURCE/relative).read_text();generated=capture_driver(relative,original)
            for line in original.splitlines():
                if 'expect(' in line or 'check(' in line:self.assertIn(line,generated)
            with self.assertRaisesRegex(RuntimeError,'Unexpected diagnostic'):
                capture_driver(relative,original+original)

    def test_cmake_deferred_overlay_changes_only_selected_drivers(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);capture=root/'capture';overlay(SOURCE,capture)
            project=root/'project';project.mkdir()
            code='cmake_minimum_required(VERSION 3.22)\nproject(SwaraXT LANGUAGES CXX)\nfunction(swaraxt_enable_warnings target)\nendfunction()\n'
            (project/'Tests').mkdir();(project/'Tests/unchanged.cpp').write_text('int unchanged=0;\n')
            targets=''
            for target,path in DRIVERS.items():targets+=f'add_executable({target} "{SOURCE/path}" unchanged.cpp)\n'
            (project/'CMakeLists.txt').write_text(code+'add_subdirectory(Tests)\n')
            (project/'Tests/CMakeLists.txt').write_text(targets)
            subprocess.run(['cmake','-S',project,'-B',root/'build','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
                '-DCMAKE_PROJECT_SwaraXT_INCLUDE='+str(capture/'entry.cmake')],check=True,stdout=subprocess.DEVNULL)
            commands=json.loads((root/'build/compile_commands.json').read_text())
            self.assertEqual(len(commands),9)
            self.assertEqual(sum(Path(c['file']).parent==capture for c in commands),5)
            self.assertEqual(sum(Path(c['file'])==project/'Tests/unchanged.cpp' for c in commands),4)
            self.assertEqual(sum('-ffp-contract=off' in c['command'] for c in commands),1)

    def test_metrics_detect_one_ulp_and_length_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'a';b=Path(d)/'b'
            a.write_bytes(struct.pack('<ff',1.,0.));b.write_bytes(struct.pack('<If',0x3f800001,0.))
            m=compare(a,b)
            self.assertFalse(m['exact']);self.assertEqual(m['first_bit_difference'],0)
            self.assertEqual(m['max_ulp'],1);self.assertEqual(m['differing_samples'],1)
            b.write_bytes(struct.pack('<f',1.))
            self.assertFalse(compare(a,b)['same_count'])
            b.write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError,'Truncated'):compare(a,b)

    def test_quantization_matches_signed_half_away_from_zero(self):
        self.assertEqual(q20(.5/1048576),1);self.assertEqual(q20(-.5/1048576),-1)
        self.assertEqual(q20(33),32*1048576)

if __name__=='__main__':unittest.main()
