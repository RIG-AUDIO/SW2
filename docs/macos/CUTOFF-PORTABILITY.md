# Second Apple floating-parser portability exception

Only Source/Plugin/SwaraXtParameterLayout.cpp changes in production: include the
existing Tuning/RealFromChars.h and replace the single floating std::from_chars
call with tuning::detail::realFromChars. No new parser, dependency, namespace or
integer-call change. The helper and pinned fast_float files remain unchanged.
The original callback body, normalization, suffix handling, validation, scaling,
clamping, parameter ID/version/range/default and all other definitions are intact.

## Expected behavior derived from the original callback

| Input | Physical cutoff before normalization |
| --- | --- |
| 800, 800 Hz, +800 Hz | 800 Hz |
| 8k, 8 kHz | 8000 Hz |
| 0.5 kHz | 500 Hz |
| 1e3 Hz | 1000 Hz |
| -5 Hz | valid finite number, clamped to 10 Hz |
| 999999 Hz | valid finite number, clamped to 20000 Hz |
| 1e999 Hz, nan Hz, inf Hz | invalid/non-finite, fallback 10 Hz |
| 800junk, 800 Hzjunk, 800,5 Hz, 1e | invalid or incomplete consumption, fallback 10 Hz |
| +, +-, ++, empty | invalid, fallback 10 Hz |

Whitespace trim and case-insensitive Hz/kHz/k suffixes are preserved. A single
leading plus is removed without a second whitespace trim; '+ 800 Hz' therefore
remains invalid. Finite numbers are clamped only after double-precision scaling;
a scaling overflow remains invalid, not the upper boundary. The host API does
not expose an acceptance boolean, so fallback and lower-bound clamping both
produce 10 Hz; classifications above are derived from the unchanged callback.

## Independent host-facing comparison

scripts/macos/cutoff/qualify.py configures pinned JUCE 9.0.1 and builds the actual
original parameter-layout translation unit from ce9d251 and the actual corrected
translation unit with the existing fallback forced. The same APVTS-backed dummy
processor retrieves the real Filter Cutoff parameter from each product layout.
No callback is copied into the test. It checks identity, version, automatable
continuous domain, default, normalization and clamping, and compares normalized,
round-tripped physical and host-published float bits for the same corpus.
Decimal-comma locale variants are executed when installed and explicitly reported
unavailable otherwise. Local validation uses GCC's supported std::from_chars.

The new Apple-only CTest exercises the corrected real layout as a required
preflight/qualification target. Existing tests/goldens and non-Apple CMake remain
unchanged. This is parameter portability evidence, not audio-reference approval.
The source-parity guard now admits the exact mechanical cutoff diff only, and
records actual_cutoff_source_sha256 in source and compiled-binary provenance.
Any other parameter-layout modification is rejected. Compiled Apple source is
NOT byte-identical to the original SWARAXT tree.

## Targeted inventory

Run scripts/macos/audit_from_chars.py. It inventories all Source C++ from_chars
calls, retains the two long-long integer overloads in TuningTable.cpp, classifies
the helper's capability/forwarding calls as guarded floating operations, and
requires exactly three wrapped product call sites (two tuning, one cutoff).
Unknown occurrences fail review. No unrelated source audit or refactoring occurs.

The full native ARM64/Intel Release, Debug, ASan/UBSan and TSan requirements and
strict AU/VST3 validators remain mandatory. Audio authority remains REVIEW_REQUIRED;
a universal Intel-hosted development build alone is never full qualification.

## Executed local evidence

Actual original/fallback layout comparison: PASS, 46 cases per locale across
five executed locale settings, zero failures. Output SHA-256 is identical for
both variants: b1a5b7aed1064f8c676eef6c9c5b256e3834f6f6745f9f20ccc957840c27a424.
Compiler: GCC 15.1.1, C++17 Release, focused layout/test TUs built with
-Wall -Wextra -Wpedantic -Werror. JUCE SHA e18f7f506c0b96f2c738a0bcd7fe6467a5005ad8.
The prior 71,602 numeric comparisons again had zero differences/allocations;
original/fallback TuningTable, tuning fuzz, quantizer and Scala corpus comparisons
all passed. Source call-site inventory COMPLETE with no unresolved floating calls.
See cutoff-validation.json for hashes and classifications. These results do not
replace native plugin validation, sanitizer runs or Mac audio reference approval.
