// SPDX-FileCopyrightText: 2026 MontroneDSP
// SPDX-License-Identifier: GPL-3.0-or-later
#include <JuceHeader.h>
#include <cstdio>
#include <type_traits>

int main()
{
    using Type = juce::AudioChannelSet::ChannelType;
    static_assert(std::is_same_v<std::underlying_type_t<Type>, unsigned int>);
    static_assert(sizeof(Type) == sizeof(unsigned int));
    static_assert(juce::AudioChannelSet::discreteChannel0 == 128);
    const auto channels = juce::AudioChannelSet::discreteChannels(896);
    const auto types = channels.getChannelTypes();
    if (types.size() != 896) return 1;
    for (int index = 0; index < types.size(); ++index)
        if (static_cast<unsigned int>(types[index]) != static_cast<unsigned int>(128 + index))
            return 1;
    juce::AudioChannelSet auProbe;
    auProbe.addChannel(static_cast<Type>(256));
    auProbe.addChannel(static_cast<Type>(257));
    if (auProbe.getTypeOfChannel(0) != static_cast<Type>(256)
        || auProbe.getTypeOfChannel(1) != static_cast<Type>(257)) return 1;
    std::puts("PASS: discrete channel IDs 128..1023 and AU 256/257 round-trip with unchanged unsigned-int ABI");
    return 0;
}
