# Intel native diagnostics: execution is separate from audio admission

The immutable universal candidate is source `3a287d0764cbbd57285582a25aa41b58ed6b03b1`, run [41924729723](https://github.com/RIG-AUDIO/SW2/actions/runs/41924729723), artifact 13370320456. Its archive SHA-256 is `4ac730262b6993d96217dd6527fe959b2bd6898f79520ffb7f514ebaf37b8968`.

The original full campaign's Intel smoke failed during AU state restore. A focused reproduction [41929213688](https://github.com/RIG-AUDIO/SW2/actions/runs/41929213688) retained the failure and a debugger stack: invalid free through JUCE state restore, preceded by duplicate/hidden RTTI diagnostics. No processor or DSP change was made.

A C++-only host visibility control [41931777044](https://github.com/RIG-AUDIO/SW2/actions/runs/41931777044) still failed. Explicit hidden visibility for both C++ and Objective-C++ in the Apple test host [41933810610](https://github.com/RIG-AUDIO/SW2/actions/runs/41933810610) passed AU and VST3 two-instance state/audio/editor/reopen lifecycles against exactly the original candidate. The five focused CTests and owned AU/login cleanup also passed. Those results establish a host symbol-isolation integration defect; they do not approve an independent Mac audio reference.

## Exact test integration exceptions

Production `Source/`, resources and dependencies remain identical to the candidate. `Tests/Apple/CMakeLists.txt` differs only by the explicit host visibility hook. `Tests/avrlib_hd/UpperRegisterOscillatorTestsMain.cpp` extends its existing POSIX guard harness to Darwin, resetting and accepting SIGBUS as well as SIGSEGV only on Apple. All ROM expectations and negative controls are retained. Its exact admitted SHA-256 is `1fcf09b4c4413d3b08470dd370e5edbce83d9b648822a1c52b5344c7b48f91f1`; any other modification is rejected by policy.

Local Clang 20 controls compile and execute the ordinary Linux path and the Apple-specific signal path with `-Wall -Wextra -Werror`. These are Linux executions, not macOS runtime qualification. A separate GCC 15 local control rejected the original guard-loop's pre-existing dangling-reference warning; no warning was disabled or unrelated test loop rewritten. Real Darwin execution is required in the native profile.

## Diagnostic campaign

The manual workflow pins macos-15-intel, Xcode 16.4, CMake 3.31.6, Ninja 1.11.1.4, JUCE 9.0.1 and deployment target 11.0. Release reuses the checksum-bound universal candidate; Debug/ASan+UBSan/TSan compile production plugin sources and the native host. Existing sanitizer sensitivity controls, compile-command instrumentation audit, mandatory CTests, strict validators and cleanup are preserved.

The diagnostic driver defers only independent audio-reference admission. It never generates or approves replacement fingerprints and does not call the strict final gate. Technical execution and `REVIEW_REQUIRED` admission are separate fields. The original full workflow, gate and reference authority implementation remain unchanged. ARM64 native profiles remain mandatory for full acceptance.
