// SPDX-FileCopyrightText: 2026 MontroneDSP
// SPDX-License-Identifier: GPL-3.0-or-later
#include <JuceHeader.h>
#include <cmath>
#include <cstdio>
#include <memory>
#include <stdexcept>

namespace {
void require(bool result, const char* message)
{
    if (!result) throw std::runtime_error(message);
    std::printf("PASS: %s\n", message);
}

void pump(int milliseconds)
{
    juce::MessageManager::getInstance()->runDispatchLoopUntil(milliseconds);
}

void render(juce::AudioPluginInstance& plugin)
{
    plugin.prepareToPlay(48000.0, 256);
    juce::AudioBuffer<float> audio(juce::jmax(2, plugin.getTotalNumOutputChannels()), 256);
    juce::MidiBuffer midi;
    double energy = 0;
    for (int block = 0; block < 128; ++block)
    {
        audio.clear();
        midi.clear();
        if (block == 0) midi.addEvent(juce::MidiMessage::noteOn(1, 60, (juce::uint8)100), 0);
        if (block == 96) midi.addEvent(juce::MidiMessage::noteOff(1, 60), 17);
        plugin.processBlock(audio, midi);
        for (int channel = 0; channel < audio.getNumChannels(); ++channel)
            for (int sample = 0; sample < audio.getNumSamples(); ++sample)
            {
                const float value = audio.getSample(channel, sample);
                if (!std::isfinite(value)) throw std::runtime_error("nonfinite plugin audio");
                energy += (double)value * value;
            }
    }
    require(energy > 1.0e-8, "actual plugin renders audible finite MIDI audio");
    plugin.releaseResources();
}

void editor(juce::AudioPluginInstance& plugin, const juce::File& screenshot)
{
    const auto closeEditor = [&plugin](juce::AudioProcessorEditor* view)
    {
        plugin.editorBeingDeleted(view);
        delete view;
    };
    std::unique_ptr<juce::AudioProcessorEditor, decltype(closeEditor)> view(
        plugin.createEditorAndMakeActive(), closeEditor);
    require(view != nullptr, "actual plugin creates editor");
    require(plugin.getActiveEditor() == view.get(), "host tracks the active plugin editor");
    view->addToDesktop(juce::ComponentPeer::windowIsTemporary);
    view->setVisible(true);
    pump(400);
    require(view->getWidth() > 100 && view->getHeight() > 100, "editor has usable dimensions");
    auto image = view->createComponentSnapshot(view->getLocalBounds());
    require(image.isValid(), "actual plugin editor snapshot exists");
    if (screenshot != juce::File())
    {
        auto stream = screenshot.createOutputStream();
        require(stream != nullptr, "snapshot output writable");
        require(juce::PNGImageFormat().writeImageToStream(image, *stream), "editor PNG saved");
    }
    view->setVisible(false);
    view->removeFromDesktop();
    view.reset();
    require(plugin.getActiveEditor() == nullptr, "host clears the active editor before deletion");
}
}

int main(int argc, char** argv)
{
    try
    {
        require(argc == 4, "arguments: format plugin-path screenshot-path");
        juce::ScopedJuceInitialiser_GUI gui;
        juce::AudioPluginFormatManager manager;
        if (juce::String(argv[1]) == "VST3") manager.addFormat(std::make_unique<juce::VST3PluginFormat>());
#if JUCE_MAC
        else if (juce::String(argv[1]) == "AU") manager.addFormat(std::make_unique<juce::AudioUnitPluginFormat>());
#endif
        else throw std::runtime_error("unsupported format");
        const bool discoveryOnly = juce::String(argv[3]) == "--discover-only";
        juce::OwnedArray<juce::PluginDescription> types;
        manager.getFormat(0)->findAllTypesForFile(types, argv[2]);
        if (discoveryOnly && types.isEmpty())
        {
            std::puts("AU_DISCOVERY_PENDING");
            return 2;
        }
        require(types.size() == 1, "exactly one actual plugin type discovered");
        if (discoveryOnly)
        {
            require(juce::String(argv[1]) == "AU", "discovery-only mode requires AU");
            require(types[0]->name == "Swara XT" && types[0]->manufacturerName == "MontroneDSP"
                        && types[0]->version == SWARAXT_EXPECTED_PRODUCT_VERSION, "discovered AU has the expected product identity");
            std::puts("AU_DISCOVERY_EXACT_PASS");
            return 0;
        }
        juce::String error;
        auto first = manager.createPluginInstance(*types[0], 48000.0, 256, error);
        if (!first) throw std::runtime_error(error.toStdString());
        auto second = manager.createPluginInstance(*types[0], 48000.0, 256, error);
        if (!second) throw std::runtime_error(error.toStdString());
        require(first->getParameters().size() > 0, "actual plugin exposes parameters");
        juce::MemoryBlock state;
        first->getStateInformation(state);
        require(state.getSize() > 0, "actual plugin serializes state");
        second->setStateInformation(state.getData(), (int)state.getSize());
        render(*first);
        render(*second);
        editor(*first, juce::File(argv[3]));
        editor(*second, {});
        first.reset();
        pump(200);
        render(*second);
        editor(*second, {});
        first = manager.createPluginInstance(*types[0], 48000.0, 256, error);
        require(first != nullptr, "first instance reopens after destruction");
        editor(*first, {});
        first.reset();
        second.reset();
        pump(200);
        std::puts("PASS: actual plugin two-instance audio/editor/state/reopen lifecycle");
        return 0;
    }
    catch (const std::exception& error)
    {
        std::fprintf(stderr, "FAIL: %s\n", error.what());
        return 1;
    }
}
