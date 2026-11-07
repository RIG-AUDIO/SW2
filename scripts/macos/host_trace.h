// SPDX-FileCopyrightText: 2026 MontroneDSP
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>
namespace swaraxt_host_trace {
inline uint32_t bits(float x) { uint32_t v; std::memcpy(&v,&x,4);return v; }
inline uint64_t bits(double x) { uint64_t v; std::memcpy(&v,&x,8);return v; }
#if defined(SWARA_HOST_TRACE_BENCH)
inline void coefficients(const float*,size_t) {}
inline void begin(double,double,int,int,int) {}
inline void state(double,int,int,int,float) {}
inline void tap(int,float,float,float,float,float,float) {}
inline void end(float,double) {}
inline void dc(float,float,float,float,float) {}
inline void looper(uint32_t,uint32_t,uint8_t,uint8_t,uint8_t,int16_t) {}
inline void design(int,int,double,double,double,double,double,double,float,double) {}
inline void normalize(int,int,double,float,float) {}
#else
struct Context {
    std::ofstream src,dc,taps,loop,designed,normalized,loopState;
    std::filesystem::path root;
    uint64_t position=0,loopPosition=0;
    std::string name;
    std::vector<float> native;
    Context(const char* label) : name(label) {
        const char* directory=std::getenv("SWARA_HOST_TRACE_DIR");
        if (!directory) throw std::runtime_error("Trace directory required");
        root=std::filesystem::path(directory);std::filesystem::create_directories(root);
        src.open(root/"src.csv");dc.open(root/"dc.csv");taps.open(root/"taps.csv");loop.open(root/"loop.csv");
        designed.open(root/"design.csv");normalized.open(root/"normalize.csv");
        src<<"sample,fraction_before,step,read_before,write,size_before,fraction_after_advance,read_after,size_after,phase,mu,result,fraction_next\n";
        dc<<"sample,input,x1,y1,pole,output\n";
        taps<<"sample,tap,input,lower,upper,mu,before,after\n";
        loop<<"sample,phase,read,first,second,fraction,output\n";
        designed<<"phase,tap,x,scaled,sinc,ratio,window,value,coefficient,sum\n";
        normalized<<"phase,tap,scale,before,after\n";
    }
    bool window() const {
        if(name=="classic") return position<=180 || (position>=18125 && position<=18160);
        if(name=="dual") return position<=350;
        return position<=350 || (position>=3040 && position<=3135);
    }
    ~Context() {
        src.flush();dc.flush();taps.flush();loop.flush();designed.flush();normalized.flush();
        if (!src.good() || !dc.good() || !taps.good() || !loop.good() || !designed.good() || !normalized.good()) std::abort();
        if (loopState.is_open()) {
            loopState.flush();
            if (!loopState.good()) std::abort();
        }
    }
};
inline Context* active=nullptr;
struct Scope {
    Context context;
    explicit Scope(const char* label):context(label) { if(active)std::abort();active=&context; }
    ~Scope() { active=nullptr; }
};
inline void coefficients(const float* data,size_t count) {
    if(!active)return;
    const auto file=active->root/"runtime-coefficients.f32";
    std::ofstream stream(file,std::ios::binary);
    stream.write(reinterpret_cast<const char*>(data),static_cast<std::streamsize>(count*4));
    if(!stream.good())std::abort();
}
inline void begin(double fraction,double step,int read,int write,int size) {
    if(active)active->src<<active->position<<','<<bits(fraction)<<','<<bits(step)<<','<<read<<','<<write<<','<<size<<',';
}
inline void state(double fraction,int read,int size,int phase,float mu) {
    if(active)active->src<<bits(fraction)<<','<<read<<','<<size<<','<<phase<<','<<bits(mu)<<',';
}
inline void tap(int index,float input,float lower,float upper,float mu,float before,float after) {
    if(active && active->window()) active->taps<<active->position<<','<<index<<','<<bits(input)<<','<<bits(lower)<<','<<bits(upper)<<','<<bits(mu)<<','<<bits(before)<<','<<bits(after)<<'\n';
}
inline void end(float output,double fraction) {
    if(active)active->src<<bits(output)<<','<<bits(fraction)<<'\n';
}
inline void dc(float input,float x1,float y1,float pole,float output) {
    if(active) { active->dc<<active->position<<','<<bits(input)<<','<<bits(x1)<<','<<bits(y1)<<','<<bits(pole)<<','<<bits(output)<<'\n';++active->position; }
}
inline void looper(uint32_t phase,uint32_t read,uint8_t a,uint8_t b,uint8_t fraction,int16_t output) {
    if(active)active->loop<<active->loopPosition++<<','<<phase<<','<<read<<','<<unsigned(a)<<','<<unsigned(b)<<','<<unsigned(fraction)<<','<<output<<'\n';
}
inline void loopBuffer(const int8_t* data,size_t count) {
    if (!active || active->loopState.is_open()) return;
    std::ofstream buffer(active->root/"looper-buffer.csv");
    buffer<<"index,byte\n";
    for (size_t i=0;i<count;++i) buffer<<i<<','<<unsigned(static_cast<uint8_t>(data[i]))<<'\n';
    buffer.flush();
    if (!buffer.good()) std::abort();
    active->loopState.open(active->root/"looper-state.csv");
    active->loopState<<"sample,phase,read,write,start,duration,increment,output\n";
}
inline void loopState(uint32_t phase,uint32_t read,uint16_t write,uint16_t start,
                      uint16_t duration,uint16_t increment,int16_t output) {
    if (active) active->loopState<<active->loopPosition++<<','<<phase<<','<<read<<','<<write<<','
        <<start<<','<<duration<<','<<increment<<','<<output<<'\n';
}
inline void design(int phase,int tap,double x,double scaled,double sinc,double ratio,double window,double value,float coefficient,double sum) {
    if(active)active->designed<<phase<<','<<tap<<','<<bits(x)<<','<<bits(scaled)<<','<<bits(sinc)<<','<<bits(ratio)<<','<<bits(window)<<','<<bits(value)<<','<<bits(coefficient)<<','<<bits(sum)<<'\n';
}
inline void normalize(int phase,int tap,double scale,float before,float after) {
    if(active)active->normalized<<phase<<','<<tap<<','<<bits(scale)<<','<<bits(before)<<','<<bits(after)<<'\n';
}
#endif
} // namespace swaraxt_host_trace
