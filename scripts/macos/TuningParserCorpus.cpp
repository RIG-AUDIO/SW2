// Copyright 2026 MontroneDSP.
// SPDX-License-Identifier: GPL-3.0-or-later
#include "Tuning/TuningTable.h"
#include <cstdio>
#include <string>
#include <vector>
int main() {
 const std::vector<std::string> tokens={"1","100.0","100,0","+100.0","-100.0","1e2","1e","1e+","0","-0","nan","inf","1e309","1e-400","4.9406564584124654e-324","2.2250738585072014e-308","9007199254740993","1.00000000000000011102230246251565404236316680908203125","3/2","3 / 2","3/2 comment","100.0!comment","100.0 suffix","100.0/2","2/0","2/3/4",""," ","++1","+-1","1,2e3","0x1p2"};
 unsigned count=0;
 for(auto syntax:{swaraxt::tuning::ScalaSyntax::legacy,swaraxt::tuning::ScalaSyntax::standard})
 for(const auto& token:tokens) for(const auto& suffix:{""," ! trailing","\t! trailing"," malformed"}) {
  const auto scl=std::string("Comparison\n2\n")+token+suffix+"\n1200.0\n";
  swaraxt::tuning::TuningSnapshot snapshot;swaraxt::tuning::ParseError error;
  const bool accepted=swaraxt::tuning::parseScalaAndKeyboard(scl.c_str(),nullptr,snapshot,error,syntax);
  std::printf("%u accepted=%d",count++,int(accepted));
  if(accepted) {
   std::vector<uint8_t> bytes;
   if(!swaraxt::tuning::writeTuningTable(snapshot,bytes,error))return 2;
   std::printf(" bytes=");for(auto b:bytes)std::printf("%02x",unsigned(b));
  }
  else std::printf(" error=%s",error.message);
  std::puts("");
 }
 return 0;
}
