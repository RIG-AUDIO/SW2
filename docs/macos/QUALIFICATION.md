# SWARA XT 1.3.0 macOS engineering

This public infrastructure adapts the Apple CI design reviewed at reference
revision 53a1e9fd16dacbac5b7b16a7e13594b540909a4e. It imports no reference history
or product source. The protected product base is
5e7b967db0b52f773f382217a72c6c0c3ff6b8f7. Except for the explicitly reviewed floating parser portability exception below, production, resources, presets,
existing test drivers/goldens and Linux/Windows workflows remain unchanged.

## Toolchain and staged evidence

macos-15 arm64 and macos-15-intel x86_64 select Xcode 16.4 explicitly.
CMake 3.31.6, Ninja package 1.11.1.4, JUCE 9.0.1 at
e18f7f506c0b96f2c738a0bcd7fe6467a5005ad8 and deployment target 11.0
are required. Image, SDK, compiler, dependency SHAs, run attempt and binary
hashes are recorded. macOS 15 execution is not macOS 11 runtime coverage.
Preflight configures current targets and runs the channel ABI/domain contract.
Universal builds retain AU and VST3 arm64/x86_64 candidates, marked UNQUALIFIED.
Native smoke exercises that same candidate with an architecture-matched host.
Release/Debug/ASan+UBSan/TSan retain full registered current regression inventory,
strict auval, pluginval and Steinberg validation, and sensitivity controls.
RTSan and Apple LSan are unsupported, not passing coverage.
Standalone is deferred, NOT_RUN; skin editor is OFF.

## Audio authority: REVIEW_REQUIRED

A: platform-independent contracts (MIDI ordering, state schemas, tuning invariants,
channel numbering, filesystem semantics, non-audio exact integer checks) retain
existing assertions without replacements.
B: native floating-point fingerprints, including current Dual SVF, mixer, SRC and
integrated DSP outputs, retain current assertions. Linux/Windows expected hashes
are not adopted as macOS authorities. A mismatch fails, never gets waived.
C: legacy exact parity and historical oscillator contracts remain comparison-only;
they do not establish current 1.3.0 macOS acceptance.

No historical 1.2.x baseline is built or used for current acceptance. All native
regression logs and JUnit records are retained when the tests execute. A failing
suite keeps its original result. Even if every current assertion passes, native
qualification and the independent full gate fail closed pending owner-reviewed
macOS authority. Candidate fingerprints cannot approve themselves. Future approval
requires raw records from repeated independent native campaigns, exact source,
architecture/profile/toolchain identities, case inventories, hashes and an explicit
reviewed authority change with negative mutation controls. The admission function
currently rejects all unapproved authorities; no approval record is fabricated.

## Public safety and release scope

Only the engineering branch triggers push CI. Manual preflight/build/smoke/full
modes are retained for eventual default-branch integration. Jobs request contents
read only, use no secrets, and never access private repositories. Development
bundles use temporary ad-hoc seals only, not Developer ID. Signing, notarization,
installer production and publication are deferred to a separate owner-approved
local Mac task. No release, tag, merge, Apple credentials or keychains are involved.
Artifacts use seven-day retention. Only runner-owned generated evidence and
candidates are uploaded; no private source archives are uploaded.

Shared CMake changes admit Apple test aggregation, enable Objective-C/Objective-C++,
and extend the existing build-owned MIDI-capacity overlay to JUCE's .mm module.
Linux/Windows branches of those hooks are unchanged. Apple uses unshared test
compilation until its current sharing implementation is separately reviewed.

## Scheduling independence

The universal candidate is cross-compiled on macos-15-intel after Intel preflight.
Its host argument is x86_64 while CMake still requests both arm64 and x86_64
and lipo verifies both slices. Smoke jobs depend on the immutable candidate;
each verifies its own native source/toolchain context before executing it.
Dedicated ARM64 preflight, smoke and all native profiles remain required.
Both preflight jobs must succeed for the full final gate. An Intel-built universal
candidate is BUILD_PASS_UNQUALIFIED, never ARM64 runtime acceptance. Different
source revisions have separate concurrency groups so an older valid queued
ARM64 request does not block a scheduling-corrected build. Same-revision runs
remain serialized. No runner queue is treated as a product compilation failure.

## Floating-point parser portability exception

Xcode 16.4 libc++ lacks floating std::from_chars. SW2 changes only the two real
calls in TuningTable.cpp to RealFromChars.h; all integer parsing, normalization,
Scala comments, token validation and non-finite rejection stay unchanged.
Linux/Windows still call std::from_chars. Apple uses SFINAE overload detection:
if the floating overload exists it is used, otherwise vendored fast_float v8.2.5
(commit 05087a303dad9c98768b33c829d398223a649bc6) parses general-format binary64.
No unpinned build-time download occurs. The MIT option and upstream notices are
included; files match the pinned UPSTREAM.json inventory. Range errors do not
commit the temporary result, preserving the standard destination-value contract.

The repository and compiled Apple source are NOT byte-identical to the original
SWARAXT Source tree. The parity guard admits only an exact mechanical replacement
of those two calls plus the exact helper/dependency hashes. It still rejects
unrelated Source, existing dependency, audio golden or resource changes.
Provenance uses EXACT_PARSER_PORTABILITY_EXCEPTION and records the actual parser
source SHA-256. Universal candidates contain compiled-source-manifest.json, with
hashes of compiler-input source files, parser helper and vendored headers, and
bind its digest in provenance.json. This exception does not approve any Mac audio
reference or relax the native full gate.

Local numerical qualification compares GCC libstdc++ std::from_chars with forced
fallback: 71,602 cases including exact binary64/error/consumption comparison and
an allocation-hook positive control. Existing tuning table, fuzz and quantizer
regressions run twice against original and fallback sources. A 256-case
legacy/standard Scala corpus compares success, errors and serialized snapshots.
Reproduce with ParserEquivalence.cpp and parser_semantics.py; result identities
are recorded in parser-validation.json. Mac preflight also builds/runs the
existing TuningTable, tuning fuzz and quantizer tests before universal compilation.
