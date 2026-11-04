# SWARA XT 1.3.0 macOS engineering

This public infrastructure adapts the Apple CI design reviewed at reference
revision 53a1e9fd16dacbac5b7b16a7e13594b540909a4e. It imports no reference history
or product source. The protected product base is
5e7b967db0b52f773f382217a72c6c0c3ff6b8f7. Production, resources, presets,
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
