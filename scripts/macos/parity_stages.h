// SPDX-FileCopyrightText: 2026 MontroneDSP
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <JuceHeader.h>
#include "Plugin/PluginProcessor.h"
#include "parity_capture.h"
#include <array>
namespace swaraxt_capture {
inline int nextStage = 0;
inline int lastStage = -1;
inline void caseName(const char* name) { std::printf("CAPTURE_CASE stage=%d name=%s\n", lastStage, name); }
struct Stages {
    swaraxt::SwaraXtEngine& engine;
    const int index = nextStage++;
    std::array<std::vector<float>, 7> values;
    explicit Stages(SwaraXtAudioProcessor& p) : engine(p.engineForTests()) {
        lastStage = index;
        floatingContext();
        engine.setDebugTapSink(this, capture);
    }
    static void capture(void* context, const swaraxt::SwaraXtEngine::DebugBlockCapture& b) {
        auto& self = *static_cast<Stages*>(context);
        const float* source[] {b.rawOsc1,b.rawOsc2,b.postShruthiMixer,b.filterOutput,b.postVca,b.vcaGain,b.vcaTarget};
        for (size_t i=0;i<self.values.size();++i)
            self.values[i].insert(self.values[i].end(),source[i],source[i]+b.samples);
    }
    ~Stages() noexcept(false) {
        engine.setDebugTapSink(nullptr,nullptr);
        const char* names[] {"osc1","osc2","mixer","filter","post","gain","target"};
        for (size_t i=0;i<values.size();++i) write("stage-"+std::to_string(index)+"-"+names[i],values[i]);
    }
};
} // namespace swaraxt_capture
