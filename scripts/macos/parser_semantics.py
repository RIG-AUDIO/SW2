# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
import subprocess,json
import argparse
parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);options=parser.parse_args()
r=Path(__file__).resolve().parents[2];out=options.output;out.mkdir(parents=True,exist_ok=True)
baseline=out/'TuningTableOriginal.cpp';baseline.write_bytes(subprocess.check_output(['git','show','da3d8e1849cdb73bd0e9ec70cbfb97c6e16c7e8a:Source/Tuning/TuningTable.cpp'],cwd=r))
results=[]
for name,drivers,args in [('tuning',['Tests/Tuning/TuningTableTestsMain.cpp'],[]),('fuzz',['Tests/Fuzz/TuningFuzzRegressionTestsMain.cpp','Tests/Fuzz/TuningFuzz.cpp'],[]),('quantizer',['Tests/Tuning/QuantizerTestsMain.cpp'],[str(r/'Source/Tuning/builtin')]),('scala-corpus',['scripts/macos/TuningParserCorpus.cpp'],[])]:
 outputs=[]
 for mode,source,defines in [('original',baseline,[]),('portable',r/'Source/Tuning/TuningTable.cpp',['-DSWARAXT_FORCE_PORTABLE_REAL_PARSER=1'])]:
  binary=out/(name+'-'+mode);cmd=['g++','-std=c++17','-O2','-Wall','-Wextra','-Wpedantic','-Werror',*defines,'-I',str(r/'Source'),*[str(r/p) for p in drivers],str(source),'-o',str(binary)]
  subprocess.run(cmd,check=True);p=subprocess.run([str(binary),*args],capture_output=True,text=True);(out/(name+'-'+mode+'.log')).write_text(p.stdout+p.stderr);assert p.returncode==0,(name,mode,p.stdout[-2000:]);outputs.append(p.stdout);results.append({'test':name,'mode':mode,'exit_code':p.returncode})
 assert outputs[0]==outputs[1],name
 print(name,'original/fallback PASS, identical output',flush=True)
(out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
