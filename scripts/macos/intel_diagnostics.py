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
from ci import Campaign, SOURCE, digest
from policy import require, safe_extract_tar, files_manifest, check_bundle, SEAL, hosted_root, owned_path

CANDIDATE_SHA='3a287d0764cbbd57285582a25aa41b58ed6b03b1'
CANDIDATE_RUN='41924729723'
CANDIDATE_ATTEMPT='1'
ARCHIVE_SHA256='4ac730262b6993d96217dd6527fe959b2bd6898f79520ffb7f514ebaf37b8968'

class DiagnosticCampaign(Campaign):
    def configure(self,juce,universal=False):
        build,config=super().configure(juce,universal)
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
        expected_tests=original_tests.replace('target_link_libraries(SwaraXTApplePluginHost PRIVATE juce::juce_audio_utils)',
            "target_link_libraries(SwaraXTApplePluginHost PRIVATE juce::juce_audio_utils)\n# Isolate the host's statically linked JUCE from loaded plugin modules.\nset_target_properties(SwaraXTApplePluginHost PROPERTIES\n    CXX_VISIBILITY_PRESET hidden VISIBILITY_INLINES_HIDDEN YES)")
        require((SOURCE/'Tests/Apple/CMakeLists.txt').read_text()==expected_tests,'Unreviewed host visibility integration')
        test_diff=subprocess.check_output(['git','diff','--name-only',CANDIDATE_SHA,'HEAD','--','Tests'],cwd=SOURCE,text=True).splitlines()
        require(test_diff==['Tests/Apple/CMakeLists.txt'],'Current regression drivers differ from approved candidate')
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
        code=super().run(name,argv,**kwargs)
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
