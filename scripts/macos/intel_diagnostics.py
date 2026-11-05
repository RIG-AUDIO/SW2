# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
"""Manual Intel diagnostics against the immutable approved universal candidate.

Technical execution is separate from reference admission; never calls the full gate.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import re
import shutil
import sys
from ci import Campaign, SOURCE, digest
from policy import require, safe_extract_tar, files_manifest, check_bundle, SEAL, hosted_root, owned_path, APPLE_GUARD_TEST, verify_apple_guard_test

CANDIDATE_SHA='3a287d0764cbbd57285582a25aa41b58ed6b03b1'
CANDIDATE_RUN='41924729723'
CANDIDATE_ATTEMPT='1'
ARCHIVE_SHA256='4ac730262b6993d96217dd6527fe959b2bd6898f79520ffb7f514ebaf37b8968'

class DiagnosticCampaign(Campaign):
    def configure(self,juce,universal=False):
        build,config=super().configure(juce,universal)
        if getattr(self.args, 'optimize_build', False):
            import compiler_cache
            before=json.loads((build/'compile_commands.json').read_text())
            inventory_before=json.loads(subprocess.check_output(['ctest','--test-dir',build,'--show-only=json-v1'],text=True))
            self.cache_tool=compiler_cache.install(self.root/'compiler-cache-tool')
            self.env=compiler_cache.configure_cache(self.root/'compiler-cache',self.env,self.args.arch+'-'+self.args.profile)
            self.run('compiler-cache-config',[self.cache_tool,'--show-config'])
            settings=(self.root/'compiler-cache-config.log').read_text()
            for name in ('sloppiness','ignore_options','remote_storage','base_dir'):
                require(any(line.endswith(name+' = ') for line in settings.splitlines()),'Unsafe compiler-cache setting: '+name)
            controls=compiler_cache.equivalence_controls(self.cache_tool,self.root/'cache-equivalence-controls',
                subprocess.check_output(['xcrun','--find','clang++'],text=True).strip(),self.env,apple=True)
            (self.root/'cache-equivalence.json').write_text(json.dumps(controls,indent=2)+'\n')
            cmake_control=compiler_cache.cmake_control(self.cache_tool,self.root/'cache-cmake-control',
                subprocess.check_output(['xcrun','--find','clang++'],text=True).strip(),self.env)
            (self.root/'cache-cmake-equivalence.json').write_text(json.dumps(cmake_control,indent=2)+'\n')
            launcher=compiler_cache.write_launcher(self.root/'compiler-launcher',self.cache_tool,juce,
                build/'generated/midi-capacity/juce_audio_utils.mm')
            self.run('configure-compiler-cache',['cmake','-S',SOURCE,'-B',build,
                *['-DCMAKE_'+language+'_COMPILER_LAUNCHER='+launcher for language in ('C','CXX','OBJC','OBJCXX')]])
            after=json.loads((build/'compile_commands.json').read_text())
            require(before==after,'Compiler launcher changed evaluated compilation semantics')
            inventory_after=json.loads(subprocess.check_output(['ctest','--test-dir',build,'--show-only=json-v1'],text=True))
            require(inventory_before==inventory_after,'Compiler cache changed mandatory CTest inventory')
            (self.root/'ctest-configured-inventory.json').write_text(json.dumps(inventory_after,indent=2)+'\n')
            (self.root/'build-graph-inventory.json').write_text(json.dumps(compiler_cache.inventory(after),indent=2)+'\n')
            self.run('complete-ninja-graph',['ninja','-C',build,'-t','graph','SwaraXTQualificationTests'])
            self.report['build_optimization']={'method':'JUCE_ONLY_PREPROCESSOR_CACHE','ccache_version':compiler_cache.VERSION,
                'ccache_commit':compiler_cache.UPSTREAM_COMMIT,'ccache_archive_sha256':compiler_cache.DARWIN_SHA256,
                'evaluated_compile_commands':'IDENTICAL','ctest_inventory':'IDENTICAL',
                'production_object_sharing':False,'parallelism':2,'timeout_seconds':10800}
            self.save()
        if self.args.task=='smoke':
            self.run('configure-host-stack-symbols',['cmake','-S',SOURCE,'-B',build,
                     '-DCMAKE_CXX_FLAGS=-g','-DCMAKE_OBJCXX_FLAGS=-g'])
        return build,config

    def seal_ci_bundles(self,bundles):
        if self.args.profile=='Release':
            return  # Release uses the original sealed candidate; no rebuilt plugins.
        return super().seal_ci_bundles(bundles)

    def verified_candidate(self):
        manifest=json.loads((self.args.candidate/'provenance.json').read_text())
        require(manifest['source_sha']==CANDIDATE_SHA and manifest['run_id']==CANDIDATE_RUN
                and manifest['run_attempt']==CANDIDATE_ATTEMPT,'Approved candidate origin mismatch')
        require(manifest['qualification_status']=='BUILD_PASS_UNQUALIFIED' and manifest['version']=='1.3.0', 'Unreviewed candidate product')
        require(manifest['ci_bundle_signature']==SEAL,'Candidate CI seal mismatch')
        require(manifest['juce_sha']==self.report['juce_sha'] and manifest['dependency_overlay']==self.report['dependency_overlay'],'Candidate toolchain overlay differs')
        require(files_manifest(self.args.candidate)==manifest['files'],'Candidate checksum inventory mismatch')
        require(digest(self.args.candidate/'compiled-source-manifest.json')==manifest['compiled_source_manifest_sha256'],'Compiled-source provenance mismatch')
        # Different CI revisions are permitted only with byte-identical product/test inputs.
        for path in ('Source','resources','third_party'):
            before=subprocess.check_output(['git','rev-parse',CANDIDATE_SHA+':'+path],cwd=SOURCE,text=True).strip()
            after=subprocess.check_output(['git','rev-parse','HEAD:'+path],cwd=SOURCE,text=True).strip()
            require(before==after,'Diagnostic checkout differs from approved candidate: '+path)
        original_tests=subprocess.check_output(['git','show',CANDIDATE_SHA+':Tests/Apple/CMakeLists.txt'],cwd=SOURCE,text=True)
        visibility_hook = "\n# Isolate the host's statically linked JUCE from loaded plugin modules.\ntarget_compile_options(SwaraXTApplePluginHost PRIVATE\n    \"$<$<COMPILE_LANGUAGE:CXX,OBJCXX>:-fvisibility=hidden;-fvisibility-inlines-hidden>\")"
        expected_tests=original_tests.replace('target_link_libraries(SwaraXTApplePluginHost PRIVATE juce::juce_audio_utils)',
            'target_link_libraries(SwaraXTApplePluginHost PRIVATE juce::juce_audio_utils)'+visibility_hook)
        require((SOURCE/'Tests/Apple/CMakeLists.txt').read_text()==expected_tests,'Unreviewed host visibility integration')
        test_diff=subprocess.check_output(['git','diff','--name-only',CANDIDATE_SHA,'HEAD','--','Tests'],cwd=SOURCE,text=True).splitlines()
        require(test_diff==['Tests/Apple/CMakeLists.txt',APPLE_GUARD_TEST],'Current regression drivers differ from approved candidate')
        verify_apple_guard_test(SOURCE)
        bundles=[self.args.candidate/'Swara XT.component',self.args.candidate/'Swara XT.vst3']
        for bundle in bundles:
            require(check_bundle(bundle,self.version,['arm64','x86_64'])==manifest['binaries'][bundle.name],'Candidate binary identity mismatch')
            self.run('verify-candidate-'+('AU' if bundle.suffix=='.component' else 'VST3'),['codesign','--verify','--deep','--strict',bundle])
        self.report['candidate_origin']={'source_sha':CANDIDATE_SHA,'run_id':CANDIDATE_RUN,'run_attempt':CANDIDATE_ATTEMPT,'archive_sha256':ARCHIVE_SHA256}
        self.report['actual_universal_candidate_checked']=True
        return bundles

    def run(self,name,argv,**kwargs):
        if name=='build-host-preflight' and self.args.profile=='Release':
            argv=[value for value in argv if value not in ('SwaraXT_AU','SwaraXT_VST3')]
        if name=='build-native-tests' and getattr(self.args,'optimize_build',False):
            build=self.root/'build'
            self.run('ninja-remaining-plan',['ninja','-C',build,'-n','SwaraXTQualificationTests'])
            plan=(self.root/'ninja-remaining-plan.log').read_text()
            steps=[int(n) for n in re.findall(r'\[\d+/(\d+)\]',plan)]
            self.report['build_optimization']['remaining_ninja_steps']=max(steps) if steps else 0
            self.save()
            argv=['/usr/bin/time','-l',*argv]
        failure=None
        try:
            code=super().run(name,argv,**kwargs)
        except BaseException as error:
            failure=error
            raise
        finally:
            if name=='build-native-tests' and getattr(self.args,'optimize_build',False):
                try:
                    ninja_log=self.root/'build/.ninja_log'
                    if ninja_log.exists():shutil.copyfile(ninja_log,self.root/'ninja-timing.log')
                    self.run('compiler-cache-statistics',[self.cache_tool,'--show-stats','--verbose'])
                    self.run('compiler-cache-counters',[self.cache_tool,'--print-stats'])
                    statistics=self.root/'compiler-cache/statistics.log'
                    if statistics.exists():
                        shutil.copyfile(statistics,self.root/'compiler-cache-invocations.log')
                    build_log=(self.root/'build-native-tests.log').read_text(errors='replace')
                    rss=re.findall(r'(\d+)\s+maximum resident set size',build_log)
                    self.report['build_optimization']['time_maximum_resident_set_size_bytes']=int(rss[-1]) if rss else None
                    self.save()
                except BaseException as error:
                    self.report['cache_statistics_error']=str(error)
                    self.save()
                    if failure is None:raise
        if name in ('actual-AU','actual-VST3') and code!=0:
            # A second focused reproduction only, before owned AU cleanup. Stack only,
            # no core dumps, environment, credential stores or raw crash-report archives.
            super().run('lldb-'+name,['xcrun','lldb','--batch','-o','run','-k','thread backtrace all','--',*map(str,argv)],timeout=600,expected=None,login=True)
        return code

    def native_reference(self,juce,config):
        self.report['audio_reference_admission']='REVIEW_REQUIRED'
        self.report['qualification_decision']='PENDING_NOT_FULLY_QUALIFIED'
        # No fingerprint generation, no approval, no changes to strict native_reference.py.
        return None

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile',choices=['smoke-repro','Release','Debug','asan-ubsan','tsan'],default='smoke-repro')
    p.add_argument('--optimize-build',action='store_true',help='Validate and measure the JUCE-only preprocessor cache')
    p.add_argument('--root',type=Path,required=True);p.add_argument('--candidate-download',type=Path,required=True)
    a=p.parse_args();hosted_root(a.root,SOURCE)
    a.candidate_download=owned_path(a.candidate_download,os.environ['RUNNER_TEMP'])
    archive=a.candidate_download/'swaraxt-unsigned-universal.tar.gz'
    require(archive.is_file() and not archive.is_symlink(),'Approved archive missing or linked')
    require(digest(archive)==ARCHIVE_SHA256,'Pinned candidate archive SHA-256 mismatch')
    extraction=Path(os.environ['RUNNER_TEMP'])/'diagnostic-candidate';safe_extract_tar(archive,extraction)
    a.candidate=extraction/'unsigned-universal';a.candidate_archive_sha256=ARCHIVE_SHA256
    a.source_sha=os.environ['GITHUB_SHA'];a.base_source_sha='5e7b967db0b52f773f382217a72c6c0c3ff6b8f7'
    a.arch='x86_64';a.mode='full';a.task='smoke' if a.profile=='smoke-repro' else 'tests'
    if a.profile=='smoke-repro':a.profile='Release'
    campaign=DiagnosticCampaign(a)
    campaign.report['diagnostic_only']=True
    campaign.report['audio_reference_admission']='REVIEW_REQUIRED'
    campaign.report['full_qualification']='PENDING'
    try:
        campaign.execute()
        campaign.report['technical_execution']='PASS'
    except BaseException:
        campaign.report['technical_execution']='FAIL'
        raise
    finally:
        campaign.save()
if __name__=='__main__':main()
