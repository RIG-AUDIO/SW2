# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
"""Targeted inventory, not a general C++ parser; unknown call sites fail review."""
import argparse
import json
from pathlib import Path
import re
root=Path(__file__).resolve().parents[2]
expected={'Source/Tuning/TuningTable.cpp':2,'Source/Tuning/RealFromChars.h':3}
records=[];counts={};unknown=[]
for path in sorted((root/'Source').rglob('*')):
 if not path.is_file() or path.suffix not in ('.h','.hpp','.cpp','.cc','.cxx','.mm','.inl'):continue
 text=path.read_text(errors='replace');name=path.relative_to(root).as_posix()
 for match in re.finditer(r'std::from_chars\s*\(',text):
  counts[name]=counts.get(name,0)+1
  if name=='Source/Tuning/TuningTable.cpp':
   kind='INTEGER_OVERLOAD';reason='parseFullInteger long long and standardPitch long long denominator'
   assert 'long long& value' in text and 'long long denominator = 1;' in text
  elif name=='Source/Tuning/RealFromChars.h':
   kind='GUARDED_FLOATING_OVERLOAD';reason='capability probe or supported-standard-library forwarding; Apple fallback retained'
  else:kind='UNRESOLVED_APPLE_PORTABILITY_RISK';reason='not in reviewed inventory';unknown.append(name)
  records.append({'file':name,'line':text.count('\n',0,match.start())+1,'classification':kind,'reason':reason})
 for match in re.finditer(r'(?<![A-Za-z])(?:tuning::)?detail::realFromChars\s*\(',text):
  records.append({'file':name,'line':text.count('\n',0,match.start())+1,'classification':'ALREADY_PORTABLY_WRAPPED'})
assert counts==expected,('STOP: review changed from_chars inventory',counts)
assert not unknown,unknown
assert sum(r['classification']=='ALREADY_PORTABLY_WRAPPED' for r in records)==3
result={'status':'COMPLETE','unresolved_apple_portability_risks':unknown,'occurrences':records}
p=argparse.ArgumentParser();p.add_argument('--output',type=Path);args=p.parse_args()
if args.output:args.output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
