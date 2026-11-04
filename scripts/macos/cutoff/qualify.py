# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare actual original/portable JUCE parameter layouts on a supported stdlib."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
p=argparse.ArgumentParser();p.add_argument('--juce',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--jobs',default='1');args=p.parse_args()
root=Path(__file__).resolve().parents[3];out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
sha=subprocess.check_output(['git','-C',str(args.juce),'rev-parse','HEAD'],text=True).strip()
assert sha=='e18f7f506c0b96f2c738a0bcd7fe6467a5005ad8','Pinned JUCE required'
original=out/'OriginalLayout.cpp';original.write_bytes(subprocess.check_output(['git','show','ce9d2512beb3398a2e628e1ae4a32650de3d87b6:Source/Plugin/SwaraXtParameterLayout.cpp'],cwd=root))
commands=[['cmake','-S',str(Path(__file__).parent),'-B',str(out/'build'),'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DJUCE_ROOT='+str(args.juce.resolve()),'-DSW2_ROOT='+str(root),'-DORIGINAL_LAYOUT='+str(original)],['cmake','--build',str(out/'build'),'--target','Cutoff-original','Cutoff-portable','--parallel',args.jobs]]
for n,cmd in enumerate(commands):
 with (out/f'build-{n}.log').open('w') as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
outputs=[]
for variant in ('original','portable'):
 result=subprocess.run([str(out/'build'/('Cutoff-'+variant))],capture_output=True,text=True)
 (out/(variant+'.log')).write_text(result.stdout+result.stderr)
 assert result.returncode==0,(variant,result.returncode,result.stdout[-2000:],result.stderr[-2000:])
 outputs.append(result.stdout)
assert outputs[0]==outputs[1],'STOP: host-visible parameter behavior differs'
result={'decision':'PASS','baseline_commit':'ce9d2512beb3398a2e628e1ae4a32650de3d87b6','juce_sha':sha,'comparison':'actual APVTS parameter ID/version/range/default; normalized, physical and host float bits; locale variants','original_output_sha256':hashlib.sha256(outputs[0].encode()).hexdigest(),'portable_output_sha256':hashlib.sha256(outputs[1].encode()).hexdigest(),'case_summary':outputs[0].splitlines()[-1],'actual_parameter_source_sha256':hashlib.sha256((root/'Source/Plugin/SwaraXtParameterLayout.cpp').read_bytes()).hexdigest(),'compiler':subprocess.check_output(['c++','--version'],text=True).splitlines()[0]}
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
