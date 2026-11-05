#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
"""Targeted Release captures. Never admits references or runs the full gate."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from ci import Campaign, SOURCE, digest
from policy import hosted_root, require

DRIVERS = {
    'SwaraXTAudioParityTests': 'Tests/AudioRegression/AudioRegressionTestsMain.cpp',
    'SwaraXTDspFxIntegratedExactParityTests': 'Tests/Parity/DspFxIntegratedExactParityTestsMain.cpp',
    'SwaraXTHostSrcExactParityTests': 'Tests/Parity/HostSrcExactParityTestsMain.cpp',
    'SwaraXTDualSvfIntegrationAudit': 'Tests/Filter/DualSvfIntegrationAuditMain.cpp',
}
SECTION2 = 'SwaraXTDualSvfSection2Tests'
REQUIRED_TESTS = (*DRIVERS, SECTION2)

def required_commands(listing):
    """Unbuilt unrelated CTest executables may legitimately lack commands."""
    commands = {}
    for test in listing['tests']:
        name = test.get('name')
        if name not in REQUIRED_TESTS:
            continue
        require(name not in commands, 'Duplicate required parity target: '+name)
        command = test.get('command')
        require(isinstance(command, list) and command and
                all(isinstance(argument, str) for argument in command) and command[0].strip(),
                'Required parity target lacks an executable command: '+name)
        commands[name] = command
    missing = sorted(set(REQUIRED_TESTS) - commands.keys())
    require(not missing, 'Missing required parity targets: '+', '.join(missing))
    return commands

def once(text, before, after):
    require(text.count(before) == 1, 'Unexpected diagnostic driver anchor: '+before)
    return text.replace(before, after, 1)

def capture_driver(path, text):
    """Only add observation; retain all original stimulus and assertions."""
    if path.endswith(('AudioRegressionTestsMain.cpp','DspFxIntegratedExactParityTestsMain.cpp')):
        text = '#include "parity_stages.h"\n'+text
        signature = 'renderProcessor' if path.endswith('AudioRegressionTestsMain.cpp') else 'render'
        anchor = 'std::vector<float> '+signature+'(SwaraXtAudioProcessor& proc, int note, bool releaseNote)\n{\n    proc.prepareToPlay(kHostRate, kBlockSize);'
        text = once(text, anchor, anchor+'\n    swaraxt_capture::Stages diagnosticStages(proc);')
        if path.endswith('AudioRegressionTestsMain.cpp'):
            anchor = '        const auto m = measure(audio, kHostRate);'
            text = once(text, anchor, '        swaraxt_capture::caseName(scenario.file);\n'+anchor)
        else:
            anchor = '    const auto h = hashBits(audio);'
            text = once(text, anchor, '    swaraxt_capture::caseName(name);\n'+anchor)
    elif path.endswith('HostSrcExactParityTestsMain.cpp'):
        text = '#include "parity_capture.h"\n'+text
        text = once(text, 'int main()\n{', 'int main()\n{\n    swaraxt_capture::floatingContext();')
        anchor = '    const auto a = convert(hostRate, native, hostSamples, regular, 1);'
        observation = '''    swaraxt_capture::write(std::string(name)+"-input", native);
    Converter coefficientProbe { SWARAXT_SRC_FIR_STOPBAND_DB };
    coefficientProbe.setStep(kNative,hostRate);
    std::vector<float> coefficients;
    for (int phase=0;phase<=Converter::kPhases;++phase) {
        const auto* row=coefficientProbe.coefficientRow(phase);
        coefficients.insert(coefficients.end(),row,row+Converter::kTaps);
    }
    swaraxt_capture::write(std::string(name)+"-coefficients",coefficients);
'''
        text = once(text,anchor,observation+anchor)
        anchor = '    const auto h = hashBits(a);'
        text = once(text,anchor,'''    swaraxt_capture::write(std::string(name)+"-output",a);
    swaraxt_capture::write(std::string(name)+"-irregular",b);
    swaraxt_capture::write(std::string(name)+"-again",again);
'''+anchor)
    elif path.endswith('DualSvfIntegrationAuditMain.cpp'):
        text = '#include "parity_capture.h"\n'+text
        text = once(text, 'int main(int argc,char** argv) {', 'int main(int argc,char** argv) {\n    swaraxt_capture::floatingContext();')
        text = once(text, '    std::vector<float> host, mixer, filtered, post, vca, target, undelayed;',
                    '    std::vector<float> host, mixer, filtered, post, vca, target, undelayed, diagnosticOsc1, diagnosticOsc2;')
        anchor = '        t.undelayed.insert(t.undelayed.end(),b.dualUndelayed,b.dualUndelayed+b.samples);'
        text = once(text, anchor, '''        t.diagnosticOsc1.insert(t.diagnosticOsc1.end(),b.rawOsc1,b.rawOsc1+b.samples);
        t.diagnosticOsc2.insert(t.diagnosticOsc2.end(),b.rawOsc2,b.rawOsc2+b.samples);
'''+anchor)
        anchor = '        const auto t=renderSection2Reference(s,fx);'
        text = once(text,anchor,anchor+'''
        static int captureIndex=0;
        const auto prefix="case-"+std::to_string(captureIndex++);
        const std::vector<float>* stages[]={&t.diagnosticOsc1,&t.diagnosticOsc2,&t.mixer,&t.undelayed,&t.filtered,&t.post,&t.vca,&t.target,&t.host};
        const char* names[]={"osc1","osc2","mixer","undelayed","filtered","post","gain","target","host"};
        for(size_t i=0;i<9;++i) swaraxt_capture::write(prefix+"-"+names[i],*stages[i]);
        std::printf("CAPTURE_DUAL %s cal=%d route=%d control=%d cut=%d res=%d fx=%d latency=%d native=%016llx expected_native=%016llx host=%016llx expected_host=%016llx\\n",
            prefix.c_str(),static_cast<int>(s.calibration),static_cast<int>(s.routing),static_cast<int>(s.control2),
            s.cutoff2,s.resonance2,fx,t.latency,static_cast<unsigned long long>(q20Hash(t.undelayed)),
            static_cast<unsigned long long>(nativeGolden),static_cast<unsigned long long>(q20Hash(t.host)),static_cast<unsigned long long>(hostGolden));
''')
    else:
        raise RuntimeError('Unknown diagnostic driver')
    return text

def overlay(source, destination):
    """Replace only four test translation units in a build-owned tree."""
    destination.mkdir(parents=True, exist_ok=False)
    records={}
    commands=[]
    for target,relative in DRIVERS.items():
        original=(source/relative).read_text()
        # Pin drivers to the completed original macOS campaign, not to new data.
        approved=subprocess.check_output(['git','show','3206c24bc93373b112e2462bc3ad0b07fe7f7589:'+relative],cwd=source,text=True)
        require(original==approved,'Diagnostic stimulus/assertions changed: '+relative)
        result=capture_driver(relative,original)
        generated=destination/Path(relative).name
        generated.write_text(result)
        records[relative]={'original_sha256':digest(source/relative),'capture_sha256':digest(generated)}
        commands.append(f'''get_target_property(items {target} SOURCES)
set(replacement)
set(replaced 0)
foreach(item IN LISTS items)
  if(item MATCHES "(^|/){Path(relative).name}$")
    list(APPEND replacement "{generated.as_posix()}")
    math(EXPR replaced "${{replaced}}+1")
  else()
    list(APPEND replacement "${{item}}")
  endif()
endforeach()
if(NOT replaced EQUAL 1)
  message(FATAL_ERROR "Unexpected capture target sources: {target}")
endif()
set_property(TARGET {target} PROPERTY SOURCES "${{replacement}}")
target_include_directories({target} PRIVATE "{(source/relative).parent.as_posix()}" "{(source/'scripts/macos').as_posix()}")
''')
    for target in ('SwaraXTAudioParityTests','SwaraXTDspFxIntegratedExactParityTests'):
        commands.append(f'target_compile_definitions({target} PRIVATE SWARAXT_ENABLE_SHRUTHI_DEBUG_TAPS=1)\n')
    commands.append(f'''add_executable(SwaraXTSrcNoContractControl "{(destination/'HostSrcExactParityTestsMain.cpp').as_posix()}")
target_include_directories(SwaraXTSrcNoContractControl PRIVATE "{(source/'Source').as_posix()}" "{(source/'Tests').as_posix()}" "{(source/'scripts/macos').as_posix()}")
target_compile_options(SwaraXTSrcNoContractControl PRIVATE -ffp-contract=off)
swaraxt_enable_warnings(SwaraXTSrcNoContractControl)
''')
    (destination/'install.cmake').write_text('\n'.join(commands))
    (destination/'entry.cmake').write_text('cmake_language(DEFER CALL include "'+(destination/'install.cmake').as_posix()+'")\n')
    (destination/'manifest.json').write_text(json.dumps(records,indent=2)+'\n')
    return records

class ParityProbe(Campaign):
    def run(self,name,argv,**kwargs):
        if name=='configure':
            argv=[*argv,'-DCMAKE_PROJECT_SwaraXT_INCLUDE='+str(self.root/'capture-drivers/entry.cmake')]
        return super().run(name,argv,**kwargs)

    def execute(self):
        self.report.update(diagnostic_only=True,full_qualification='BLOCKED',audio_reference_admission='REVIEW_REQUIRED')
        try:
            juce=self.prepare()
            # Product source must remain byte-identical to the universal candidate.
            for path in ('Source','resources','third_party'):
                before=subprocess.check_output(['git','rev-parse','3a287d0764cbbd57285582a25aa41b58ed6b03b1:'+path],cwd=SOURCE,text=True).strip()
                after=subprocess.check_output(['git','rev-parse','HEAD:'+path],cwd=SOURCE,text=True).strip()
                require(before==after,'Product changed: '+path)
            self.report['capture_overlay']=overlay(SOURCE,self.root/'capture-drivers')
            build,_=self.configure(juce)
            targets=[*DRIVERS,SECTION2,'SwaraXTSrcNoContractControl']
            self.run('build-targeted-parity',['cmake','--build',build,'--parallel','2','--target',*targets],timeout=7200)
            listing=json.loads(subprocess.check_output(['ctest','--test-dir',build,'--show-only=json-v1'],text=True))
            (self.root/'ctest-inventory.json').write_text(json.dumps(listing,indent=2)+'\n')
            self.report['unrelated_tests_without_command']=[t['name'] for t in listing['tests']
                if t.get('name') not in REQUIRED_TESTS and not t.get('command')]
            self.report['test_inventory']=[t['name'] for t in listing['tests']]
            self.save()
            commands=required_commands(listing)
            compiled=json.loads((build/'compile_commands.json').read_text())
            self.report['compiled_input_sha256']={item['file']:digest(Path(item['file'])) for item in compiled if Path(item['file']).is_file()}
            self.report['target_executables']={}
            self.report['executions']=[]
            for target in [*DRIVERS,SECTION2]:
                binary=Path(commands[target][0])
                require(binary.is_file() and os.access(binary,os.X_OK),'Required parity executable is unavailable: '+target)
                slices=subprocess.check_output(['lipo','-archs',binary],text=True).split()
                require(slices==[self.args.arch],'Wrong diagnostic executable architecture')
                self.report['target_executables'][target]={'sha256':digest(binary),'architectures':slices}
                for repeat in range(2):
                    directory=self.root/'captures'/target/('run'+str(repeat+1))
                    directory.mkdir(parents=True)
                    env={**self.env,'SWARA_CURRENT_REFERENCE_DIR':str(directory)}
                    name=target+'-run'+str(repeat+1)
                    if repeat==0:
                        argv=['ctest','--test-dir',build,'-R','^'+target+'$','--output-on-failure','--no-tests=error',
                              '--test-output-size-passed','16777216','--test-output-size-failed','16777216','--output-junit',self.root/(name+'.xml')]
                    else:
                        argv=commands[target]
                    code=self.run(name,argv,expected=None,env=env,timeout=1800)
                    self.report['executions'].append({'name':name,'exit_code':int(code),'expected_reference_failures_possible':True})
                    require(code in ((0,8) if repeat==0 else (0,1)),'Diagnostic crashed or timed out: '+name)
                    self.save()
            controls=list(build.rglob('SwaraXTSrcNoContractControl'))
            require(len(controls)==1,'Missing SRC contraction control')
            require(subprocess.check_output(['lipo','-archs',controls[0]],text=True).split()==[self.args.arch],'Wrong contraction control architecture')
            self.report['src_no_contract_binary_sha256']=digest(controls[0])
            directory=self.root/'captures/SRC-no-contract';directory.mkdir(parents=True)
            code=self.run('SRC-no-contract',[controls[0]],expected=None,env={**self.env,'SWARA_CURRENT_REFERENCE_DIR':str(directory)})
            require(code in (0,1),'SRC contraction control crashed')
            self.report['src_no_contract_exit_code']=int(code)
            self.report['capture_manifest']={str(p.relative_to(self.root/'captures')):{'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted((self.root/'captures').rglob('*')) if p.is_file()}
            self.run('compare-repeat-captures',['python3',SOURCE/'scripts/macos/parity_metrics.py','--repeat-root',self.root/'captures','--output',self.root/'repeat-metrics.json'])
            self.report['repeated_renders_bitwise_equal']=json.loads((self.root/'repeat-metrics.json').read_text())['all_repeats_bitwise_equal']
            require(not subprocess.check_output(['git','status','--porcelain'],cwd=SOURCE,text=True).strip(),'Diagnostic source became dirty')
            self.report['decision']='DIAGNOSTIC_CAPTURE_COMPLETE_NOT_QUALIFIED'
        except BaseException as error:
            self.report['decision']='DIAGNOSTIC_INCOMPLETE';self.report['failure']=str(error)
            raise
        finally:
            self.save()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--arch',choices=('x86_64','arm64'),required=True)
    args=parser.parse_args()
    hosted_root(args.root,SOURCE)
    args.profile='Release';args.task='parity-capture';args.mode='diagnostic'
    args.source_sha=os.environ['GITHUB_SHA'];args.base_source_sha='5e7b967db0b52f773f382217a72c6c0c3ff6b8f7'
    ParityProbe(args).execute()

if __name__=='__main__':main()
