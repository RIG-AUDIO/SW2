# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
juce_add_console_app(SwaraXTApplePluginHost PRODUCT_NAME "SwaraXTApplePluginHost")
juce_generate_juce_header(SwaraXTApplePluginHost)
target_sources(SwaraXTApplePluginHost PRIVATE PluginHost.cpp)
target_compile_definitions(SwaraXTApplePluginHost PRIVATE
    JUCE_PLUGINHOST_AU=1 JUCE_PLUGINHOST_VST3=1 JUCE_MODAL_LOOPS_PERMITTED=1
    JUCE_WEB_BROWSER=0 JUCE_USE_CURL=0)
target_compile_definitions(SwaraXTApplePluginHost PRIVATE
    SWARAXT_EXPECTED_PRODUCT_VERSION="${PROJECT_VERSION}")
target_link_libraries(SwaraXTApplePluginHost PRIVATE juce::juce_audio_utils)
# Isolate the host's statically linked JUCE from loaded plugin modules.
target_compile_options(SwaraXTApplePluginHost PRIVATE
    "$<$<COMPILE_LANGUAGE:CXX,OBJCXX>:-fvisibility=hidden;-fvisibility-inlines-hidden>")

juce_add_console_app(SwaraXTChannelTypeContractTests PRODUCT_NAME "SwaraXTChannelTypeContractTests")
juce_generate_juce_header(SwaraXTChannelTypeContractTests)
target_sources(SwaraXTChannelTypeContractTests PRIVATE ChannelTypeContract.cpp)
target_compile_definitions(SwaraXTChannelTypeContractTests PRIVATE JUCE_USE_CURL=0 JUCE_WEB_BROWSER=0)
target_link_libraries(SwaraXTChannelTypeContractTests PRIVATE juce::juce_audio_basics)
add_test(NAME SwaraXTChannelTypeContractTests COMMAND SwaraXTChannelTypeContractTests)
set_tests_properties(SwaraXTChannelTypeContractTests PROPERTIES TIMEOUT 60 LABELS sanitizer)
add_dependencies(SwaraXTQualificationTests SwaraXTChannelTypeContractTests)

# Exercise the actual APVTS parameter layout and host-facing cutoff conversion.
juce_add_console_app(SwaraXTCutoffParameterTests PRODUCT_NAME "SwaraXTCutoffParameterTests")
juce_generate_juce_header(SwaraXTCutoffParameterTests)
target_sources(SwaraXTCutoffParameterTests PRIVATE
    "${CMAKE_SOURCE_DIR}/scripts/macos/cutoff/CutoffParameterTests.cpp"
    "${CMAKE_SOURCE_DIR}/Source/Plugin/SwaraXtParameterLayout.cpp")
swaraxt_configure_shruthi_target(SwaraXTCutoffParameterTests)
target_compile_definitions(SwaraXTCutoffParameterTests PRIVATE
    JUCE_WEB_BROWSER=0 JUCE_USE_CURL=0 JUCE_VST3_CAN_REPLACE_VST2=0
    SWARAXT_FORCE_PORTABLE_REAL_PARSER=1)
target_link_libraries(SwaraXTCutoffParameterTests PRIVATE juce::juce_audio_processors)
swaraxt_enable_warnings_as_errors(SwaraXTCutoffParameterTests)
add_test(NAME SwaraXTCutoffParameterTests COMMAND SwaraXTCutoffParameterTests)
set_tests_properties(SwaraXTCutoffParameterTests PROPERTIES TIMEOUT 120 LABELS quick)
add_dependencies(SwaraXTQualificationTests SwaraXTCutoffParameterTests)
