#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
"""Three representative runtime host traces, not native-reference admission."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from ci import Campaign,SOURCE,digest
from parity_probe import once
from policy import require,hosted_root

BASELINE='99885a8eeaaa0d0e6773ca11abf15237786218d4'
TARGETS={'classic':'SwaraXTAudioParityTests','dual':'SwaraXTDualSvfIntegrationAudit','looper':'SwaraXTDspFxIntegratedExactParityTests'}
DRIVERS={'classic':'Tests/AudioRegression/AudioRegressionTestsMain.cpp','dual':'Tests/Filter/DualSvfIntegrationAuditMain.cpp','looper':'Tests/Parity/DspFxIntegratedExactParityTestsMain.cpp'}

def patched_source(relative,text,strict=False):
    if relative=='Engine/SampleRate/PolyphaseFirResampler.h':
        text='#include "host_trace.h"\n'+text
        text=once(text,'            sum += value;',
            '            sum += value;\n            swaraxt_host_trace::design(phase,tap,x,scaled,sinc,ratio,window,value,row[tap],sum);')
        text=once(text,'''        for (int tap = 0; tap < kTaps; ++tap)
            row[tap] = static_cast<float>(static_cast<double>(row[tap]) * scale);''',
            '''        for (int tap = 0; tap < kTaps; ++tap) {
            const float before=row[tap];
            row[tap] = static_cast<float>(static_cast<double>(row[tap]) * scale);
            swaraxt_host_trace::normalize(phase,tap,scale,before,row[tap]);
        }''')
        text=once(text,'    step_ = safeInternal / safeHost;',
            '    swaraxt_host_trace::coefficients(coeff_->data(),coeff_->size());\n    step_ = safeInternal / safeHost;')
        text=once(text,'    const int maxAdvances = 2 + static_cast<int>(std::ceil(step_)) + 8;',
            '    swaraxt_host_trace::begin(fraction_,step_,readIndex_,writeIndex_,size_);\n    const int maxAdvances = 2 + static_cast<int>(std::ceil(step_)) + 8;')
        anchor='        const float* upper = lower + kTaps;'
        text=once(text,anchor,anchor+'\n        swaraxt_host_trace::state(fraction_,readIndex_,size_,phase,mu);')
        anchor='''        for (int tap = 0; tap < kTaps; ++tap)
            accumulator += at(tap) * (lower[tap] + mu * (upper[tap] - lower[tap]));'''
        text=once(text,anchor,'''        for (int tap = 0; tap < kTaps; ++tap) {
            const float diagnosticBefore=accumulator;
            accumulator += at(tap) * (lower[tap] + mu * (upper[tap] - lower[tap]));
            swaraxt_host_trace::tap(tap,at(tap),lower[tap],upper[tap],mu,diagnosticBefore,accumulator);
        }''')
        text=once(text,'    return std::isfinite(accumulator) ? accumulator : 0.0f;',
            '    swaraxt_host_trace::end(accumulator,fraction_);\n    return std::isfinite(accumulator) ? accumulator : 0.0f;')
        if strict:
            text=once(text,'float PolyphaseFirResampler<T, P, I>::readInterpolated() noexcept\n{',
                'float PolyphaseFirResampler<T, P, I>::readInterpolated() noexcept\n{\n#pragma clang fp contract(off)')
    elif relative=='Engine/SampleRate/HostResampler.cpp':
        text='#include "host_trace.h"\n'+text
        anchor='    const float y = sample - x1_ + pole_ * y1_;'
        text=once(text,anchor,anchor+'\n    swaraxt_host_trace::dc(sample,x1_,y1_,pole_,y);')
        if strict:text=once(text,'float DcBlocker::process(float sample) noexcept\n{','float DcBlocker::process(float sample) noexcept\n{\n#pragma clang fp contract(off)')
    elif relative=='Engine/DspBoard/BoardEffects.cpp':
        text='#include "host_trace.h"\n'+text
        anchor='        loopPhase_ = phaseAdd(loopPhase_, increment);'
        text=once(text,anchor,'        swaraxt_host_trace::looper(loopPhase_,read,static_cast<uint8_t>(line_[read]),static_cast<uint8_t>(line_[read+1]),static_cast<uint8_t>(loopPhase_),sample);\n'+anchor)
    return text

def driver(source,case):
    path=source/DRIVERS[case]
    text=path.read_text()
    prefix='#include "host_trace.h"\n#include "parity_stages.h"\n#define main originalRegressionMain\n#include "'+path.as_posix()+'"\n#undef main\n'
    if case=='classic':
        body='''
    swaraxt_host_trace::Scope scope("classic");
    SwaraXtAudioProcessor proc;
    configureBasicPatch(proc,shruthi::WAVEFORM_SAW,shruthi::WAVEFORM_NONE,0,0,20000.f,0.f);
    swaraxt_capture::Stages stages(proc);
    const auto audio=renderProcessor(proc,60,true);
    swaraxt_capture::write("final",audio);
    swaraxt::test::currentRenderOutput("01_basic_saw.wav",audio,expect);
    const auto* expected=swaraxt_current_golden::find(swaraxt_current_golden::kClassic,swaraxt_current_golden::kClassicCount,"Test A basic saw");
    const auto measured=measure(audio,kHostRate);
    expect(expected && measured.hash==expected->hash && audio.size()==expected->samples,"original current Classic anchor");
    expect(measured.invalidCount==0,"original final render finite");
    expect(measured.peak>1.e-4f,"original final render non-silent");
    return gFailures?1:0;'''
    elif case=='dual':
        body='''
    Sel selected;selected.enabled=true;selected.routing=Route::serial;selected.control2=Control::relative;selected.cutoff2=52;
    Trace trace;
    { swaraxt_host_trace::Scope scope("dual");trace=renderSection2Reference(selected,0); }
    swaraxt_capture::write("final",trace.host);
    swaraxt_capture::write("native",trace.post);
    swaraxt_capture::write("undelayed",trace.undelayed);
    check(q20Hash(trace.undelayed)==dualRelativeNativeGoldens[0][0],"original native anchor");
    check(q20Hash(trace.host)==dualRelativeGoldens[0][0],"original host anchor");
    fixedPipeline(trace,48000,true,0,4,true);
    return failures?1:0;'''
    else:
        start=text.index('    {\n        SwaraXtAudioProcessor proc;\n        configureSaw(proc);\n        setInt(proc, swaraxt::IDs::dspFxProgram, 15);')
        end=text.index('        golden("looper_replay", replay, 2048);',start)+len('        golden("looper_replay", replay, 2048);\n    }')
        body=text[start:end]
        body=once(body,'        proc.prepareToPlay(kHostRate, kBlockSize);','        swaraxt_host_trace::Scope scope("looper");\n        swaraxt_capture::Stages stages(proc);\n        proc.prepareToPlay(kHostRate, kBlockSize);')
        body=once(body,'        golden("looper_replay", replay, 2048);','        swaraxt_capture::write("final",replay);\n        golden("looper_replay", replay, 2048);')
        body+='\n    return gFailures?1:0;'
    original_call='char name[]="original";char* args[]={name};return originalRegressionMain(1,args);' if case=='dual' else 'return originalRegressionMain();'
    return prefix+'int main() {\n    juce::ScopedJuceInitialiser_GUI init;\n    if(std::getenv("SWARA_ORIGINAL_TARGET")) {'+original_call+'}\n'+body+'\n}\n'

def overlay(source,destination,strict=False):
    destination.mkdir(parents=True,exist_ok=False)
    shutil.copytree(source/'Source',destination/'Source')
    # Several production headers use relative paths into the pinned dependency tree.
    (destination/'third_party').symlink_to(source/'third_party',target_is_directory=True)
    records={}
    for p in (destination/'Source').rglob('*'):
        if not p.is_file():continue
        relative=p.relative_to(destination/'Source').as_posix()
        original=(source/'Source'/relative).read_bytes()
        changed=patched_source(relative,original.decode(),strict).encode() if relative in (
            'Engine/SampleRate/PolyphaseFirResampler.h','Engine/SampleRate/HostResampler.cpp','Engine/DspBoard/BoardEffects.cpp') else original
        p.write_bytes(changed)
        records['Source/'+relative]={'original_sha256':digest(source/'Source'/relative),'compiled_sha256':digest(p)}
    cmake=[]
    for case,target in TARGETS.items():
        generated=destination/(case+'.cpp');generated.write_text(driver(source,case))
        original_name=Path(DRIVERS[case]).name
        cmake.append(f'''get_target_property(items {target} SOURCES)
set(replacement)
foreach(item IN LISTS items)
  if(item MATCHES "(^|/){original_name}$")
    list(APPEND replacement "{generated.as_posix()}")
  elseif(item MATCHES "^{source.as_posix()}/Source/")
    string(REPLACE "{source.as_posix()}/Source/" "{destination.as_posix()}/Source/" item "${{item}}")
    list(APPEND replacement "${{item}}")
  else()
    list(APPEND replacement "${{item}}")
  endif()
endforeach()
set_property(TARGET {target} PROPERTY SOURCES "${{replacement}}")
target_include_directories({target} BEFORE PRIVATE "{destination.as_posix()}/Source" "{source.as_posix()}/scripts/macos")
target_compile_definitions({target} PRIVATE SWARAXT_ENABLE_SHRUTHI_DEBUG_TAPS=1)
''')
    cmake.append(f'''add_executable(SwaraXTHostBoundaryBench "{source.as_posix()}/scripts/macos/host_boundary_bench.cpp" "{destination.as_posix()}/Source/Engine/SampleRate/HostResampler.cpp")
target_compile_definitions(SwaraXTHostBoundaryBench PRIVATE SWARA_HOST_TRACE_BENCH=1)
target_include_directories(SwaraXTHostBoundaryBench BEFORE PRIVATE "{destination.as_posix()}/Source" "{source.as_posix()}/scripts/macos")
''')
    (destination/'install.cmake').write_text('\n'.join(cmake))
    (destination/'entry.cmake').write_text('cmake_language(DEFER CALL include "'+str(destination/'install.cmake')+'")\n')
    (destination/'manifest.json').write_text(json.dumps(records,indent=2)+'\n')
    return records

class BoundaryCampaign(Campaign):
    def run(self,name,argv,**kwargs):
        if name=='configure':
            argv=[*argv,'-DCMAKE_PROJECT_SwaraXT_INCLUDE='+str(self.overlay_root/'entry.cmake')]
            name='configure-'+self.variant
        return super().run(name,argv,**kwargs)

    def execute(self):
        self.report.update(diagnostic_only=True,full_qualification='BLOCKED',audio_reference_admission='REVIEW_REQUIRED',policies_selected=False)
        try:
            juce=self.prepare()
            require(not subprocess.check_output(['git','diff','--name-only',BASELINE,'HEAD','--','Source','resources','third_party'],cwd=SOURCE,text=True).strip(),'Product differs from preserved captures')
            baselines=json.loads((SOURCE/'scripts/macos/host_boundary_baseline.json').read_text())[self.args.arch]
            self.report['variants']={}
            self.overlay_root=self.root/'runtime-overlay'
            for variant in ('native','strict-host-experiment'):
                self.variant=variant
                # Strict variant changes only two build-owned function-scoped pragmas.
                if variant=='native':manifest=overlay(SOURCE,self.overlay_root)
                else:
                    for relative in ('Engine/SampleRate/PolyphaseFirResampler.h','Engine/SampleRate/HostResampler.cpp'):
                        (self.overlay_root/'Source'/relative).write_text(patched_source(relative,(SOURCE/'Source'/relative).read_text(),True))
                    manifest={name:{**value,'compiled_sha256':digest(self.overlay_root/name)} for name,value in manifest.items()}
                (self.root/(variant+'-compiled-source.json')).write_text(json.dumps(manifest,indent=2)+'\n')
                build,_=self.configure(juce)
                shutil.copyfile(build/'compile_commands.json',self.root/(variant+'-compile-commands.json'))
                compiled=json.loads((build/'compile_commands.json').read_text())
                for target in TARGETS.values():
                    inputs={entry['file'] for entry in compiled if f'CMakeFiles/{target}.dir/' in entry['command']}
                    for relative in ('Engine/SwaraXtEngine.cpp','Engine/SampleRate/HostResampler.cpp','Engine/DspBoard/BoardEffects.cpp'):
                        require(str(self.overlay_root/'Source'/relative) in inputs and str(SOURCE/'Source'/relative) not in inputs,
                                'Runtime overlay is not active for '+target+': '+relative)
                self.run('build-'+variant,['cmake','--build',build,'--parallel','2','--target',*TARGETS.values(),'SwaraXTHostBoundaryBench'],timeout=7200)
                listing=json.loads(subprocess.check_output(['ctest','--test-dir',build,'--show-only=json-v1'],text=True))
                (self.root/(variant+'-inventory.json')).write_text(json.dumps(listing,indent=2)+'\n')
                commands={t['name']:t['command'] for t in listing['tests'] if t['name'] in TARGETS.values()}
                require(set(commands)==set(TARGETS.values()),'Required runtime target missing')
                record={'cases':{}}
                self.report['variants'][variant]=record
                if variant=='native' and self.args.arch=='x86_64':
                    self.run('intel-original-integration',['ctest','--test-dir',build,'-R','^SwaraXTDualSvfIntegrationAudit$','--output-on-failure','--no-tests=error','--output-junit',self.root/'intel-integration.xml'],
                        env={**self.env,'SWARA_ORIGINAL_TARGET':'1'},expected=0,timeout=600)
                    record['original_full_integration']='PASS'
                for case,target in TARGETS.items():
                    binary=Path(commands[target][0]);require(binary.is_file(),'Runtime executable missing')
                    require(subprocess.check_output(['lipo','-archs',binary],text=True).split()==[self.args.arch],'Wrong native architecture')
                    directory=self.root/'boundary'/variant/case;directory.mkdir(parents=True)
                    env={**self.env,'SWARA_HOST_TRACE_DIR':str(directory),'SWARA_CURRENT_REFERENCE_DIR':str(directory)}
                    code=self.run(variant+'-'+case,[binary],expected=None,env=env,timeout=600)
                    require(code in (0,1),'Runtime diagnostic crashed or timed out')
                    baseline_equal=digest(directory/'final.f32')==baselines[case]
                    require(variant!='native' or baseline_equal,'Observation changed the preserved native output: '+case)
                    record['cases'][case]={'original_assertion_exit_code':int(code),'baseline_output_identical':baseline_equal,'binary_sha256':digest(binary)}
                    self.save()
                benches=list(build.rglob('SwaraXTHostBoundaryBench'));require(len(benches)==1,'Benchmark missing')
                self.run('cpu-'+variant,[benches[0]],timeout=300)
                self.report['variants'][variant]=record;self.save()
            self.report['capture_manifest']={p.relative_to(self.root/'boundary').as_posix():{'bytes':p.stat().st_size,'sha256':digest(p)} for p in (self.root/'boundary').rglob('*') if p.is_file()}
            require(not subprocess.check_output(['git','status','--porcelain'],cwd=SOURCE,text=True).strip(),'Repository source became dirty')
            self.report['decision']='HOST_BOUNDARY_DIAGNOSTICS_COMPLETE_NOT_QUALIFIED'
        except BaseException as error:
            self.report['decision']='HOST_BOUNDARY_INCOMPLETE';self.report['failure']=str(error);raise
        finally:self.save()

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--arch',choices=('arm64','x86_64'),required=True);parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args();hosted_root(args.root,SOURCE)
    args.profile='Release';args.task='host-boundary';args.mode='diagnostic';args.source_sha=os.environ['GITHUB_SHA'];args.base_source_sha='5e7b967db0b52f773f382217a72c6c0c3ff6b8f7'
    BoundaryCampaign(args).execute()
if __name__=='__main__':main()
