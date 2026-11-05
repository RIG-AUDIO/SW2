# Native regression build optimization

## Baseline and choice

Four native Intel profiles at `8e14825101096fd93785fb136be9ed7f2a11dc20` exceeded the 10,800-second regression-build limit. The non-Release remaining Ninja plan was 4697 steps; Release, which reused the universal candidate instead of prebuilding product targets, had 4731 remaining steps. All four native AU/VST3 lifecycles passed. Release validators passed. The full CTest inventory and final instrumentation audit were not reached.

The captured Release compilation database has 4926 commands for 212 unique source files: 2398 production commands (35 files), 2155 JUCE commands (40 files), 146 generated commands (two files), and 227 other commands (135 files). There are 965 Objective-C++ commands and 87 commands containing LTO. JUCE alone has 41 definition groups, 76 ordered include groups and 229 complete evaluated compiler-environment signatures (excluding only source/output operands). Source filename identity is not an equivalence proof. Prior runs did not record compiler peak memory; no retrospective memory value is inferred.

Linux's existing `SWARAXT_SHARE_TEST_JUCE` groups modules by modal-loop configuration. Its production sharing uses direct CMake properties, normalizes generated include paths, and rewrites test-mode entry files. Those rules are not enabled or copied to Apple. All existing CMake target definitions, source lists, generated headers, include order, links, visibility, optimization, assertions and diagnostics are preserved.

The first optimization is a **JUCE-only build-local preprocessor cache**. It leaves the complete Ninja graph intact: the expected scheduled step count does not decrease. The measured improvement must come from fewer actual compiler executions and shorter elapsed time, not from omitted targets. Production and ROM compilation remain uncached. Only the isolated pinned JUCE module tree and generated `juce_audio_utils.mm` are eligible. No static/object libraries are merged.

## Reproducibility and semantic boundaries

Tool: [ccache 4.14.2](https://github.com/ccache/ccache/releases/tag/v4.14.2), exact upstream commit `360543256991b0df7b5ad1822bd08f8d4ae2aa90`; Darwin archive SHA-256 `cf240009630b605b775c7c5c7b7105a3b196c79f31af322c1557969aa28003fc`. The extracted upstream license/notices are retained with the tool; the tool/cache is not uploaded. There is no unpinned Homebrew install.

[ccache's documented preprocessor mode](https://ccache.dev/manual/4.14.html#_the_preprocessor_mode) keys reuse on compiler identity, preprocessor output, code-generation options and diagnostics. Compiler content hashing is enabled. Direct/depend modes are disabled. No sloppiness, ignored options, path rewriting or remote storage is allowed. Inherited cache configuration variables are removed. The cache starts cold within one runner-owned build, with an architecture/profile namespace; no object or cache is reused across runners, architectures, compilers or profiles.

Before compilation, the driver compares the entire evaluated CMake compile database and CTest inventory before/after installing the launcher and requires exact equality. The launcher preserves compiler arguments. Independent cached-versus-fresh object comparisons cover unused/effective macros, active header changes, optimization, PIC/visibility, Objective-C++, Debug symbols and both sanitizer configurations. A local CMake build independently verifies cached objects and identical evaluated commands. The same controls run under Xcode before the real campaign.

The complete Ninja dependency graph, source/environment inventory, remaining dry-run plan, per-call cache statistics, original build/test logs, source parity, and current CTest inventory are retained. Existing post-build instrumentation assertions remain mandatory. Cache configuration/registration is not proof of completed compilation or test execution.

## Timeout cleanup

`policy.run_process` delegates to `processes.py`. Each command runs beneath a reserved session-leader supervisor. The controller does not reap that supervisor before its final group signal, so the owned PGID cannot be recycled into an unrelated group. Normal completed commands with no remaining child receive no signals. Remaining group members receive bounded TERM/KILL handling; ESRCH is verified against the final inventory, while EPERM is recorded separately and fails cleanup. The original return code (including timeout 124) is retained. Campaign and login-worker propagation reject cleanup failures without replacing that original code. Controller loss closes an ownership pipe and causes the supervisor to terminate its own session group.

Per-command JSON reports contain group ownership, signals/errors, remaining group members, original status, duration and one-second sampled session/group/compiler RSS. No environment dumps or raw credential/diagnostic archives are collected. A focused `/usr/bin/time -l` wrapper additionally records the OS-reported maximum resident set size of the regression build. Sampled aggregate RSS is identified as sampled, not an exact aggregate peak.

Local regressions cover normal/nonzero exit, timeout, already-exited groups, ESRCH, injected EPERM, cancellation, a TERM-resistant child surviving its parent, ownership reservation until the last signal, and propagation of original timeout plus cleanup failure. The exact original runner EPERM cause is still unknown; the test reproduces its error path without asserting an unverified OS cause.

## Execution policy

First dispatch only Intel Release with `optimize-build=true`. Reuse the approved universal AU/VST3 candidate; do not rebuild it or sign a replacement. Keep parallelism 2 and the original build timeout. If the build completes, run the unchanged complete CTest inventory. No Debug/ASan/UBSan/TSan campaign is authorized by a cache configuration success alone: first demonstrate real safe, practical improvement.

The original full workflow, independent gate and reference-authority implementation are unchanged. All Intel and ARM64 native profiles, strict validators and independent Mac audio authority remain mandatory. Reference admission remains `REVIEW_REQUIRED`; no candidate fingerprint approves itself. No DSP, parser, presets, goldens, authoritative SWARAXT or private SWPV changes, release, merge, Apple credentials, signing/notarization, deletion or archival are part of this optimization.

## Bootstrap integration correction

[41982122311](https://github.com/RIG-AUDIO/SW2/actions/runs/41982122311) failed in launcher reconfiguration, before native regression compilation. The original compound launcher value contained semicolons. Pinned JUCE's `extras/Build/juceaide/CMakeLists.txt:120-138` forwards it through `list(APPEND PASSTHROUGH_ARGS ...)` and an unquoted list expansion; `--launch` became a CMake argument. Both cached/fresh numerical object controls and the independent CMake comparison passed on the actual Mac, and all process cleanup records were successful.

The launcher is now a single runner-owned executable path. Its shell wrapper forwards all compiler arguments without CMake list separators. A regression reproduces the original recursive-forwarding failure and requires the corrected path (including a space) to survive. The real local CMake object/evaluated-command comparison also passes with this wrapper. No JUCE patch, product-source change, profile expansion or timeout increase is involved.

## Actual focused result and measurement limit

[41983219568](https://github.com/RIG-AUDIO/SW2/actions/runs/41983219568), executed CI SHA `4a785bc9685349b375c8c7bbdeb068c3670056de`, passed the corrected bootstrap, 39 infrastructure tests, cached/fresh object controls, CMake object comparison, exact evaluated-compile database equality and identical 136-case CTest inventory. It retained the complete Ninja graph. Actual AU/VST3 lifecycle, strict auval, VST3 pluginval and Steinberg validation passed.

AU pluginval failed in **Editor Automation**, exit 9, with an abort assertion in `-[AppleParavirtCommandBuffer endCurrentChunk]`, `AppleParavirtCommandBuffer.mm:248`. The root cause is not established. The immutable candidate and pluginval binary were checksum-verified; the candidate was not rebuilt. [Failure evidence](https://github.com/RIG-AUDIO/SW2/actions/runs/41983219568/artifacts/13394773847) is preserved. No validation assertion or required GUI test was bypassed.

The regression build and full CTest execution were **NOT_RUN** because native validator preflight failed. No regression-build duration, optimized compiler-execution count, full instrumentation audit or performance PASS is claimed. The cold graph still has 4926 configured compiler commands for 212 unique files; cache reuse does not reduce scheduled Ninja steps. Baseline step count is 4697 for the other profiles and 4731 for the comparable Release regression build.

Inspection of the recorded memory data exposed a process-observer limitation: Ninja subcommands use separate process groups. The follow-up observer counts all groups in the reserved session; memory must not be inferred from the earlier initial-group-only values. A real local Ninja timeout control confirms nested groups are observed and cooperative cancellation removes them. An independently grouped, noncooperating child is explicitly reported as a cleanup failure with original timeout 124 retained; the controller never guesses ownership of another group's recyclable PGID. Such failure blocks further qualification and requires ephemeral-runner teardown. The test releases its own deliberately stubborn child cooperatively. New sessions detached before observation are outside this session containment guarantee.

The session-observer correction and retention of `.ninja_log` for future per-command/link timing are locally validated follow-ups, not changes executed in run 41983219568. No additional CI attempt or sanitizer profile was started after the validator failure. Isolated LTO overhead and compiler peak memory for the unexecuted regression build remain unmeasured. Production compile environments, test inventory, source and goldens remain unchanged.

## Independent build/CTest probe

The outstanding compilation measurement uses the explicitly named `Release-build-probe` profile with `optimize-build=true`. This is a build/CTest substage, not a native-qualification profile. It validates the immutable candidate's origin, configures the same complete regression graph, builds `SwaraXTQualificationTests`, runs the original compilation/instrumentation audit, and executes the unchanged full CTest inventory. No test target is dropped or rebaselined. The ordinary native profile still requires actual hosts/validators before its regressions; the helper's extraction does not change that order or those assertions.

The build probe always records the unresolved AU Editor Automation failure from run 41983219568, `native_validation=NOT_RUN_IN_BUILD_PROBE`, and `full_qualification=BLOCKED`, even if its compilation/CTest substage passes. Its stage/decision cannot substitute for a native profile in the independent final gate. Release-only probe dispatch does not schedule Debug or sanitizer profiles. The previously failed validation campaign remains preserved. This separation permits the user-requested build-cost measurement without treating a failed validator as passed or running another full native campaign.

The measured regression cache counters subtract the post-configuration baseline, so juceaide bootstrap activity is not misreported as regression-build reuse. The full Ninja timing log is retained for per-command and link analysis; an isolated LTO/no-LTO comparison is not performed and no incremental LTO cost is inferred from aggregate link time.

## ARM64 diagnostic build requested by the owner

The manual workflow now accepts an explicit architecture. `arm64` selects the supported `macos-15` ARM64 label; `x86_64` retains `macos-15-intel` ([GitHub runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)). The existing Intel run is not restarted. Architecture is part of the concurrency and evidence identity. Each hosted runner uses a fresh architecture/profile-specific cache, and the pinned universal candidate is verified independently.

The Python driver requires the actual host architecture to match, passes that architecture to the real CMake build and both independent cache controls, and records actual RAM/CPU capacity. No cross-architecture object reuse is permitted. Following a complete build, every registered compiled test executable below the build directory is inspected with `lipo`, hashed and required to contain exactly its requested native architecture before CTest executes. External Python/CMake test tools remain external tools; their tests still execute in the unchanged CTest inventory.

The ARM64 build probe has the same qualification limits as Intel. In particular, the known AU pluginval failure is explicitly identified as Intel evidence; the ARM64 probe does not pretend that native AU/VST3 validation was executed. All ARM64 native Release/Debug/ASan/UBSan/TSan and independent audio-reference requirements remain mandatory. A queued valid ARM64 job must be left queued rather than manually cancelled for waiting.
