// Copyright 2026 MontroneDSP.
// SPDX-License-Identifier: GPL-3.0-or-later
#define SWARAXT_FORCE_PORTABLE_REAL_PARSER 1
#include "Tuning/RealFromChars.h"
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <new>
#include <string>
#include <vector>
static bool track = false;
static unsigned allocations = 0;
[[gnu::noinline]] void* operator new(std::size_t n) { if(track) ++allocations; if(auto* p=std::malloc(n)) return p; throw std::bad_alloc(); }
[[gnu::noinline]] void* operator new[](std::size_t n) { return ::operator new(n); }
[[gnu::noinline]] void operator delete(void* p) noexcept { std::free(p); }
[[gnu::noinline]] void operator delete[](void* p) noexcept { std::free(p); }
[[gnu::noinline]] void operator delete(void* p, std::size_t) noexcept { std::free(p); }
[[gnu::noinline]] void operator delete[](void* p, std::size_t) noexcept { std::free(p); }
static uint64_t bits(double x) { uint64_t b; std::memcpy(&b,&x,8); return b; }
int main() {
 std::vector<std::string> cases={"","0","-0","+0","1","-1","+1",".5","1.","100.125","100,125","1e3","-1.25E-5","1e","1e+","1e-","1e+2x"," 1","\t1","1 ","nan","-nan","NAN(payload)","nan(snan)","inf","-infinity","1e309","1e-400","2.2250738585072014e-308","2.225073858507201e-308","4.9406564584124654e-324","2.4703282292062327e-324","2.4703282292062328e-324","1.7976931348623157e308","1.7976931348623159e308","9007199254740993","1.00000000000000011102230246251565404236316680908203125","3/2","100.0 ! comment","--1","+-1","1..2","0x1p2"};
 uint64_t rng=0x5377617261ULL;
 for(int n=0;n<25000;++n) {
  rng^=rng<<13;rng^=rng>>7;rng^=rng<<17;
  std::string s=(n%2?"-":"")+std::to_string(rng)+"."+std::to_string(rng>>5)+"e"+std::to_string(n%800-400);
  cases.push_back(s); cases.push_back(s+"junk");
  if(n<500) for(size_t i=0;i<s.size();++i) cases.push_back(s.substr(0,i));
 }
 track=true; void* control=::operator new(1); ::operator delete(control); track=false;
 if(allocations!=1) return 2;
 allocations=0;
 unsigned failures=0;
 for(const auto& text:cases) {
  double a=123.25,b=a; const char* first=text.data(); const char* last=first+text.size();
  track=true; auto x=std::from_chars(first,last,a,std::chars_format::general);
  auto y=swaraxt::tuning::detail::realFromChars(first,last,b); track=false;
  if(x.ec!=y.ec || x.ptr-first!=y.ptr-first || bits(a)!=bits(b)) {
   if(failures++<20) std::printf("DIFFERENCE %s ec=%d/%d consumed=%td/%td bits=%llx/%llx\n",text.c_str(),int(x.ec),int(y.ec),x.ptr-first,y.ptr-first,(unsigned long long)bits(a),(unsigned long long)bits(b));
  }
 }
 std::printf("cases=%zu differences=%u parser_allocations=%u\n",cases.size(),failures,allocations);
 return failures || allocations ? 1:0;
}
