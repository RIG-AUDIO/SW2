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

Per-command JSON reports contain group ownership, signals/errors, remaining group members, original status, duration and one-second sampled group/compiler RSS. No environment dumps or raw credential/diagnostic archives are collected. A focused `/usr/bin/time -l` wrapper additionally records the OS-reported maximum resident set size of the regression build. Sampled aggregate RSS is identified as sampled, not an exact aggregate peak.

Local regressions cover normal/nonzero exit, timeout, already-exited groups, ESRCH, injected EPERM, cancellation, a TERM-resistant child surviving its parent, ownership reservation until the last signal, and propagation of original timeout plus cleanup failure. The exact original runner EPERM cause is still unknown; the test reproduces its error path without asserting an unverified OS cause.

## Execution policy

First dispatch only Intel Release with `optimize-build=true`. Reuse the approved universal AU/VST3 candidate; do not rebuild it or sign a replacement. Keep parallelism 2 and the original build timeout. If the build completes, run the unchanged complete CTest inventory. No Debug/ASan/UBSan/TSan campaign is authorized by a cache configuration success alone: first demonstrate real safe, practical improvement.

The original full workflow, independent gate and reference-authority implementation are unchanged. All Intel and ARM64 native profiles, strict validators and independent Mac audio authority remain mandatory. Reference admission remains `REVIEW_REQUIRED`; no candidate fingerprint approves itself. No DSP, parser, presets, goldens, authoritative SWARAXT or private SWPV changes, release, merge, Apple credentials, signing/notarization, deletion or archival are part of this optimization.

## Bootstrap integration correction

[41982122311](https://github.com/RIG-AUDIO/SW2/actions/runs/41982122311) failed in launcher reconfiguration, before native regression compilation. The original compound launcher value contained semicolons. Pinned JUCE's `extras/Build/juceaide/CMakeLists.txt:120-138` forwards it through `list(APPEND PASSTHROUGH_ARGS ...)` and an unquoted list expansion; `--launch` became a CMake argument. Both cached/fresh numerical object controls and the independent CMake comparison passed on the actual Mac, and all process cleanup records were successful.

The launcher is now a single runner-owned executable path. Its shell wrapper forwards all compiler arguments without CMake list separators. A regression reproduces the original recursive-forwarding failure and requires the corrected path (including a space) to survive. The real local CMake object/evaluated-command comparison also passes with this wrapper. No JUCE patch, product-source change, profile expansion or timeout increase is involved.
