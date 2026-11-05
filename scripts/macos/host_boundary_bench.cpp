// SPDX-FileCopyrightText: 2026 MontroneDSP
// SPDX-License-Identifier: GPL-3.0-or-later
#include "Engine/SampleRate/PolyphaseFirResampler.h"
#include "Engine/SampleRate/HostResampler.h"
#include <cstdio>
#include <ctime>
#include <cstring>
#include <cstdint>
int main() {
    using Converter=swaraxt::PolyphaseFirResampler<256,256,true>;
    for(double rate : {44100.,48000.}) for(int trial=0;trial<5;++trial) {
        Converter src;src.setStep(20000000./510.,rate);src.reset();
        swaraxt::DcBlocker dc;dc.prepare(rate);
        uint32_t random=0x21;uint64_t hash=1469598103934665603ull;
        constexpr int samples=262144;
        const auto before=std::clock();
        for(int i=0;i<samples;++i) {
            while(src.size()<src.queueTargetSize()) {
                random=random*1664525u+1013904223u;
                src.push(static_cast<float>(static_cast<int>(random>>24)-128)/128.f);
            }
            const float y=dc.process(src.readInterpolated());
            uint32_t bits;std::memcpy(&bits,&y,4);hash^=bits;hash*=1099511628211ull;
        }
        const double seconds=static_cast<double>(std::clock()-before)/CLOCKS_PER_SEC;
        std::printf("BENCH rate=%.0f trial=%d samples=%d cpu_seconds=%.9f ns_per_sample=%.3f hash=%016llx\n",rate,trial,samples,seconds,seconds*1.e9/samples,static_cast<unsigned long long>(hash));
    }
}
