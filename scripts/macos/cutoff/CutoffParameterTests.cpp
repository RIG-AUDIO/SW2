// Copyright 2026 MontroneDSP.
// SPDX-License-Identifier: GPL-3.0-or-later
#include "Plugin/SwaraXtParameterLayout.h"
#include <clocale>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
class Processor final : public juce::AudioProcessor {
public:
 juce::AudioProcessorValueTreeState state {*this, nullptr, "PARAMETERS", swaraxt::createSwaraXtParameterLayout()};
 const juce::String getName() const override {return "Cutoff parameter contract";}
 void prepareToPlay(double,int) override {} void releaseResources() override {}
 void processBlock(juce::AudioBuffer<float>&,juce::MidiBuffer&) override {}
 bool acceptsMidi() const override {return false;} bool producesMidi() const override {return false;}
 bool hasEditor() const override {return false;} juce::AudioProcessorEditor* createEditor() override {return nullptr;}
 double getTailLengthSeconds() const override {return 0;}
 int getNumPrograms() override {return 1;} int getCurrentProgram() override {return 0;}
 void setCurrentProgram(int) override {} const juce::String getProgramName(int) override {return {};}
 void changeProgramName(int,const juce::String&) override {}
 void getStateInformation(juce::MemoryBlock&) override {} void setStateInformation(const void*,int) override {}
};
static uint32_t bits(float f) { uint32_t b;std::memcpy(&b,&f,sizeof(b));return b; }
int main() {
 Processor processor;
 auto* parameter=processor.state.getParameter(swaraxt::IDs::filterCutoff);
 if(!parameter || parameter->getParameterID()!="filter_cutoff" || parameter->getVersionHint()!=1) return 2;
 if(!dynamic_cast<juce::AudioParameterFloat*>(parameter) || parameter->getName(128)!="Filter Cutoff" || parameter->isDiscrete())return 4;
 auto& range=parameter->getNormalisableRange();
 if(range.start!=10.0f || range.end!=20000.0f || range.interval!=0.0f || !parameter->isAutomatable())return 3;
 if(bits(parameter->getDefaultValue())!=bits(range.convertTo0to1(8000.0f)))return 5;
 std::printf("identity=%s version=%d min=%.0f max=%.0f default=%08x\n",parameter->getParameterID().toRawUTF8(),parameter->getVersionHint(),double(range.start),double(range.end),bits(parameter->getDefaultValue()));
 struct Case {const char* text;float expected;};
 const Case cases[]={{"800",800},{"800 Hz",800},{"8k",8000},{"8 kHz",8000},{"0.5 kHz",500},{"+800 Hz",800},{"-5 Hz",10},{"999999 Hz",20000},{"1e3 Hz",1000},{"1e999 Hz",10},{"nan Hz",10},{"inf Hz",10},{"800junk",10},{"800 Hzjunk",10},{"800,5 Hz",10},{"1e",10},{"+",10},{"+-",10},{"++",10},{"",10},{"  +800 HZ \t",800},{"8 K",8000},{" 0.5 KhZ ",500},{"+ 800 Hz",10},{"++800 Hz",10},{"--800 Hz",10},{"+-800 Hz",10},{"-+800 Hz",10},{"0 Hz",10},{"10Hz",10},{"20kHz",20000},{"0.009kHz",10},{"20.0001kHz",20000},{"-0",10},{"1e-999 Hz",10},{"800.5 hz",800.5f},{"NaN(payload) Hz",10},{"-inf Hz",10},{"800\nHz",800},{"1e307 kHz",10},{"1e308 Hz",20000},{".5k",500},{"1.k",1000},{"8kk",10},{"800hz hz",10},{"1000.000030517578125 Hz",1000}};
 const char* originalLocale=std::setlocale(LC_NUMERIC,nullptr);const std::string saved=originalLocale?originalLocale:"C";
 unsigned failures=0,locales=0;
 for(const auto* locale:{"C","de_DE.utf8","fr_FR.utf8","de_DE.UTF-8","fr_FR.UTF-8"}) {
  if(!std::setlocale(LC_NUMERIC,locale)) {std::printf("LOCALE_UNAVAILABLE %s\n",locale);continue;}
  ++locales;
  unsigned n=0;
  for(const auto& c:cases) {
   const auto normalized=parameter->getValueForText(c.text);
   const auto expectedNormalized=range.convertTo0to1(c.expected);
   const auto physical=range.convertFrom0to1(normalized);
   parameter->setValueNotifyingHost(normalized);
   const auto published=parameter->getValue();
   const bool okay=bits(normalized)==bits(expectedNormalized) && std::isfinite(physical)
       && std::abs(physical-c.expected)<=std::max(0.002f,c.expected*0.000002f);
   if(!okay) {std::printf("FAIL case=%u expected=%08x actual=%08x\n",n,bits(expectedNormalized),bits(normalized));++failures;}
   std::printf("case=%u normalized=%08x physical=%08x host=%08x\n",n++,bits(normalized),bits(physical),bits(published));
  }
 }
 std::setlocale(LC_NUMERIC,saved.c_str());
 std::printf("cases_per_locale=%zu executed_locales=%u failures=%u\n",sizeof(cases)/sizeof(cases[0]),locales,failures);
 return failures?1:0;
}
