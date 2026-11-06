# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
import csv
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from host_boundary import BASELINE,overlay,patched_source,driver,TARGETS,loop_capture,output_results
from policy import verify_dual_integration_selection,DUAL_INTEGRATION_TEST,BASE_SHA

SOURCE=Path(__file__).resolve().parents[2]

class HostBoundaryControls(unittest.TestCase):
    def test_integration_selector_platform_matrix(self):
        text=(SOURCE/DUAL_INTEGRATION_TEST).read_text().split('#if defined(_MSC_VER)',1)[1].split('#endif',1)[0]
        text='#if defined(_MSC_VER)'+text+'#endif\n'
        text=text.replace('#include "DualSvfCurrentLinuxGoldens.h" // Host values independently qualified on MSVC.','CURRENT_HOST').replace('#include "DualSvfCurrentWindowsTimingGoldens.h"','CURRENT_NATIVE').replace('#include "DualSvfSection2Goldens.h"','HISTORICAL')
        for macros,current in ((['__linux__'],True),(['_MSC_VER'],True),(['__APPLE__','__x86_64__'],True),(['__APPLE__','__aarch64__'],False)):
            result=subprocess.check_output(['c++','-E','-P','-undef','-x','c++',*['-D'+v for v in macros],'-'],input=text,text=True)
            self.assertEqual('CURRENT_NATIVE' in result,current)
            self.assertEqual('CURRENT_HOST' in result,current)
            self.assertEqual('HISTORICAL' in result,not current)
        verify_dual_integration_selection(SOURCE)

    def test_selector_exception_rejects_unrelated_changes(self):
        original=subprocess.check_output(['git','show',BASE_SHA+':'+DUAL_INTEGRATION_TEST],cwd=SOURCE,text=True)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/DUAL_INTEGRATION_TEST;p.parent.mkdir(parents=True)
            p.write_text((SOURCE/DUAL_INTEGRATION_TEST).read_text()+'\n// extra\n')
            with patch('policy.subprocess.check_output',return_value=original):
                with self.assertRaisesRegex(RuntimeError,'Unreviewed integration'):verify_dual_integration_selection(d)

    def test_scoped_experiment_changes_only_two_functions(self):
        paths=('Engine/SampleRate/PolyphaseFirResampler.h','Engine/SampleRate/HostResampler.cpp','Engine/DspBoard/BoardEffects.cpp')
        for relative in paths:
            text=subprocess.check_output(['git','show',BASELINE+':Source/'+relative],cwd=SOURCE,text=True)
            observed=patched_source(relative,text)
            experimental=patched_source(relative,text,True)
            if relative.endswith('BoardEffects.cpp'):self.assertEqual(observed,experimental)
            else:self.assertEqual(observed,experimental.replace('\n#pragma clang fp contract(off)',''))
        self.assertIn('originalRegressionMain(1,args)',driver(SOURCE,'dual'))
        self.assertIn('hasValidLoop()',driver(SOURCE,'looper'))
        self.assertIn('golden("looper_replay", replay, 2048)',driver(SOURCE,'looper'))

    def test_cmake_maps_only_selected_production_sources(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);owned=root/'overlay';records=overlay(SOURCE,owned)
            self.assertEqual((owned/'Source/Tuning/../../third_party').resolve(),SOURCE/'third_party')
            changed=[p for p,r in records.items() if r['original_sha256']!=r['compiled_sha256']]
            self.assertEqual(len(changed),3)
            project=root/'project';project.mkdir()
            code='cmake_minimum_required(VERSION 3.22)\nproject(SwaraXT LANGUAGES CXX)\n'
            from host_boundary import DRIVERS
            for case,target in TARGETS.items():
                code+=f'add_executable({target} "{SOURCE/DRIVERS[case]}" "{SOURCE}/Source/Engine/SampleRate/HostResampler.cpp")\n'
            (project/'CMakeLists.txt').write_text(code)
            subprocess.run(['cmake','-S',project,'-B',root/'build','-DCMAKE_EXPORT_COMPILE_COMMANDS=ON','-DCMAKE_PROJECT_SwaraXT_INCLUDE='+str(owned/'entry.cmake')],check=True,stdout=subprocess.DEVNULL)
            import json
            entries=json.loads((root/'build/compile_commands.json').read_text())
            self.assertFalse(any(str(SOURCE/'Source') in item['file'] for item in entries))
            self.assertEqual(sum(Path(item['file']).is_relative_to(owned) for item in entries),7)

    def test_observer_retains_original_arithmetic_and_records_runtime(self):
        clang=shutil.which('clang++');self.assertIsNotNone(clang)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);owned=root/'overlay';overlay(SOURCE,owned)
            program=root/'probe.cpp'
            program.write_text('''#include "Engine/SampleRate/PolyphaseFirResampler.h"
#include "Engine/SampleRate/HostResampler.h"
#include <fstream>
int main(int,char** args){
#ifdef OBSERVE
swaraxt_host_trace::Scope scope("classic");
#endif
swaraxt::PolyphaseFirResampler<256,256,true> src;src.setStep(20000000./510.,44100);src.reset();swaraxt::DcBlocker dc;dc.prepare(44100);
std::ofstream out(args[1],std::ios::binary);unsigned random=33;
for(int i=0;i<1024;++i){while(src.size()<src.queueTargetSize()){random=random*1664525u+1013904223u;src.push(float(int(random>>24)-128)/128.f);}float y=dc.process(src.readInterpolated());out.write(reinterpret_cast<char*>(&y),4);}}
''')
            for label,include,defines in [('original',SOURCE/'Source',[]),('observed',owned/'Source',['-DOBSERVE'])]:
                subprocess.run([clang,'-std=c++17','-O3','-Wall','-Wextra','-Werror',*defines,'-I'+str(include),'-I'+str(SOURCE/'scripts/macos'),str(program),str(include/'Engine/SampleRate/HostResampler.cpp'),'-o',str(root/label)],check=True)
                subprocess.run([root/label,root/(label+'.f32')],env={**os.environ,'SWARA_HOST_TRACE_DIR':str(root/'trace')},check=True)
            self.assertEqual((root/'original.f32').read_bytes(),(root/'observed.f32').read_bytes())
            for name,count in [('src',1024),('dc',1024),('taps',181*256)]:
                with (root/'trace'/(name+'.csv')).open() as file:rows=list(csv.DictReader(file))
                self.assertEqual(len(rows),count)
                self.assertTrue(all(None not in row for row in rows))
            self.assertEqual((root/'trace/runtime-coefficients.f32').stat().st_size,257*256*4)

    def test_decision_preserves_kernel_sources_and_original_fixture_assertions(self):
        for relative in ('Engine/SampleRate/PolyphaseFirResampler.h','Engine/SampleRate/HostResampler.cpp'):
            original=subprocess.check_output(['git','show',BASELINE+':Source/'+relative],cwd=SOURCE,text=True)
            self.assertEqual(patched_source(relative,original,decision=True),original)
            strict=patched_source(relative,original,strict=True,decision=True)
            self.assertEqual(strict.count('#pragma clang fp contract(off)'),1)
            self.assertEqual(strict.replace('\n#pragma clang fp contract(off)',''),original)
            production=(SOURCE/'Source'/relative).read_text()
            guard='#if defined(__APPLE__) && defined(__clang__) && defined(__arm64__)'
            start=production.index(guard)
            end=production.index('#endif',start)+len('#endif')
            self.assertEqual(production[:start]+'#pragma clang fp contract(off)'+production[end:],strict)
        original=(SOURCE/'Tests/Parity/DspFxIntegratedExactParityTestsMain.cpp').read_text()
        generated=driver(SOURCE,'looper',decision=True)
        for line in original.splitlines():
            if 'expect(' in line or 'golden(' in line:self.assertIn(line,generated)
        self.assertIn('swaraxt_capture::Stages stages(proc);',generated)

    def test_exact_output_comparison_requires_each_capture(self):
        import hashlib
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);sample=b'\x00\x00\x80\x3f'
            (root/'required.f32').write_bytes(sample)
            sha=hashlib.sha256(sample).hexdigest()
            expected={'required.f32':{'native':sha,'intel':'0'*64}}
            result=output_results(root,expected)['required.f32']
            self.assertTrue(result['native_baseline_identical'])
            self.assertFalse(result['intel_current_identical'])
            expected['missing.f32']=expected['required.f32']
            with self.assertRaisesRegex(RuntimeError,'Missing or invalid required output missing.f32'):
                output_results(root,expected)

    def test_looper_observer_records_complete_buffer_and_playback_state(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);owned=root/'overlay';overlay(SOURCE,owned,decision=True)
            program=root/'loop.cpp'
            program.write_text('''#include "host_trace.h"
#include "Engine/DspBoard/BoardEffects.h"
int main() {
    swaraxt_host_trace::Scope scope("looper");
    swaraxt::board::BoardEffects fx;
    fx.reset(true);
    swaraxt::board::Block block{};
    for (int i=0;i<20;++i) fx.process(block,swaraxt::board::Effect::looper,64,0,120);
    for (int i=0;i<4;++i) fx.process(block,swaraxt::board::Effect::looper,64,128,120);
    std::ofstream native(scope.context.root/"stage-0-post.f32",std::ios::binary);
    const float sample=0.f;
    native.write(reinterpret_cast<const char*>(&sample),sizeof(sample));
}
''')
            board=owned/'Source/Engine/DspBoard'
            subprocess.run(['clang++','-std=c++17','-O3','-Wall','-Wextra','-Werror',
                '-I'+str(owned/'Source'),'-I'+str(SOURCE/'scripts/macos'),str(program),
                str(board/'BoardEffects.cpp'),str(board/'BoardResources.cpp'),'-o',str(root/'loop')],check=True)
            subprocess.run([root/'loop'],env={**os.environ,'SWARA_HOST_TRACE_DIR':str(root/'trace')},check=True)
            result=loop_capture(root/'trace')
            self.assertEqual(result['buffer_bytes'],1281)
            self.assertEqual(result['replay_state_samples'],160)

if __name__=='__main__':unittest.main()
