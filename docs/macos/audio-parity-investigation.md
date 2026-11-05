# Native audio parity investigation — original evidence

Investigation checkpoint, not reference approval or full qualification. Production DSP, presets, resources and golden headers are unchanged. The proven parser fallback is unchanged. PR #1 remains draft and unmerged.

## Preserved campaigns

| Architecture | Source | Executed tests | Original evidence |
|---|---|---|---|
| Intel | `8c1a26e3f313711919b02078dc48d6d7f89fc4af` | 134 PASS / 2 FAIL | [run 41987415872](https://github.com/RIG-AUDIO/SW2/actions/runs/41987415872), [artifact](https://github.com/RIG-AUDIO/SW2/actions/runs/41987415872/artifacts/13402932775) |
| ARM64 | `3206c24bc93373b112e2462bc3ad0b07fe7f7589` | 131 PASS / 5 FAIL | [run 41997015252](https://github.com/RIG-AUDIO/SW2/actions/runs/41997015252), [artifact](https://github.com/RIG-AUDIO/SW2/actions/runs/41997015252/artifacts/13404626065) |

Both compiled successfully with Xcode 16.4 / Apple Clang 17, SDK 15.5, JUCE `e18f7f506c0b96f2c738a0bcd7fe6467a5005ad8`, Release `-O3`, C++17, minimum macOS 11.0. Product trees match the universal candidate at `3a287d0764cbbd57285582a25aa41b58ed6b03b1`. Intel image/macOS 15.7.9 and ARM image/macOS 15.8.2 differ; architecture is not the only variable. Complete metadata, report/CTest/compile-command hashes, failed assertion counts and 72 case records are in [the machine-readable comparison](audio-parity-original-evidence.json).

## Intel Dual SVF — confirmed selector defect

All 12 Intel host Q20 fingerprints match the existing current table, and none match the historical table selected by the former Apple branch. This conclusion also uses the independently retained causal provenance: factory0 public Sub64/Noise0 maps to firmware32/0; the historical two-assignment mixer control restores the old fingerprints exactly. Current raw compiler/repeat comparisons and independent Q20 rehashes are documented in `Tests/References/DualSvfCurrentLinuxProvenance.json`. Current JUCE 9.0.1 MSVC corroboration is in `DualSvfCurrentWindowsTimingProvenance.json`. The Linux provenance initially used JUCE 9.0.4; it is not alone used to assert identical Mac builds.

The correction changes one preprocessor condition in `DualSvfSection2TestsMain.cpp`, adding only Apple x86_64. Linux and MSVC still select the same current header; Apple ARM64 still selects its previous header and remains unresolved. No new hash is generated or admitted. Platform-matrix preprocessing tests and an exact original-text transformation protect this exception. Native execution of the corrected selector is still required.

## Integration — unresolved native anchors

Each original architecture reports 48 pre-delay and 12 migrated-host fingerprint failures. All other exact assertions passed, including indexed delay, pending-tail/reset/prepare/wake controls, reported latency, and independent fixed-pipeline FX/gain/SRC/DC replay. These passing controls do not validate the acoustic baseline.

The original integration test selects historical MSVC anchors on Apple. The current Windows provenance independently identifies obsolete mixer state: its historical-control/current comparison first differs at mixer/native sample 0 and host sample 314. That is Windows causal evidence, not a measured first divergence on macOS. Original Mac logs did not print per-case native hashes or retain raw samples. Therefore this patch does not change the integration reference selector. It adds build-owned observation of all 48 existing fixtures and retains every assertion.

## ARM64 — unresolved numerical causes

Classic: 7/8 fingerprint failures. Host SRC: 24/30 failures (all six silence fixtures match). Integrated FX: 21/22 failures (`seq_ringmod` matches). Dual SVF: all 12 differ from Intel, current and historical headers. These are observations, not evidence that an architecture difference is harmless. There is no approved new ARM64 reference.

No classification of `PLATFORM_NUMERICAL_DIFFERENCE` or `ACTUAL_DSP_REGRESSION` is made from checksums alone. First differing samples, RMS/absolute/relative errors, ULPs and Q20 differences are absent from the original artifacts and remain unmeasured until raw captures execute.

## Targeted diagnostic method

Use manual `Release-parity-capture` on each native architecture. The existing macOS workflow uses Xcode 16.4 and the pinned dependency/deployment configuration. It builds only the five affected test targets plus one standalone SRC contraction control. It does not rebuild universal bundles, run all 136 tests, run sanitizers, install an AU, call a validator or invoke the final gate.

Four test translation units receive build-owned observation overlays, pinned to the original ARM campaign source. All assertions and original stimuli are retained. Classic/FX use the existing input/output capture contract plus existing production debug taps. Dual integration records oscillators, mixer, pre-delay, delayed/filter output, post-FX, gain/target and final host samples for each fixture. Host SRC records inputs, FIR coefficient rows, regular/irregular/repeat outputs. Debug taps are explicitly enabled for Classic/FX; this is a diagnostic compilation configuration and must not be mistaken for byte-identical test binaries. Production source bytes remain unchanged.

Each target runs twice, preserving original CTest failures separately from capture completion. Logs map output cases to stage indices and record FP rounding/control-register state. Exact compiler commands, actual source hashes, generated-driver hashes, native executable hashes/slices and all capture SHA-256 values are retained. A separate SRC-only target uses `-ffp-contract=off` as a causal control; it does not alter production flags or other tests.

`parity_metrics.py` independently computes binary32, Classic Q23 and Dual Q20 fingerprints, first/number of bit differences, max absolute/RMS/relative errors, ULP distribution, Q23/Q20 differences and onset indices. It compares repeat files and the SRC contraction control without acceptance tolerances. Its directory interface also compares downloaded Intel/ARM captures. Missing counts/files and non-finite data are reported, never interpreted as PASS. Equal repeat captures establish repeatability only, not correctness.

Local validation: 86 infrastructure controls PASS; original, capture-enabled and no-contract Host SRC executables each PASS all 30 existing cases on Linux, with identical golden lines and raw capture/control files. These controls do not establish the Apple cause. No new authority or full qualification can be produced by the capture workflow.

## Per-case fingerprints

All values below are hexadecimal. Classic uses signed Q23 byte-FNV (clamp [-8,8], lround(x*2^23)); SRC/FX use binary32 byte-FNV; Dual uses its documented word-Q20 hash. ARM rows remain UNRESOLVED. Intel Dual rows are REFERENCE_SELECTION_DEFECT. Matching current hashes in other families preserve original passing evidence only.

| Family / case | Current expected | Intel observed | ARM64 observed |
|---|---|---|---|
| classic / Test A basic saw | `e49a2f5d8a7090f9` | `e49a2f5d8a7090f9` | `f9725e4f5d9bb16f` |
| classic / Test B basic square | `608f87853120af8e` | `608f87853120af8e` | `9c73de87bfbf918c` |
| classic / Test C two oscillators | `2e5f9d73aeaa1820` | `2e5f9d73aeaa1820` | `891cf7e6718ed085` |
| classic / Test F filter low resonance | `0099139bef0f1690` | `0099139bef0f1690` | `3ae4cc8a316fa919` |
| classic / Test G filter high resonance | `1ac4a6fabf9a3da5` | `1ac4a6fabf9a3da5` | `1038dce5870f43fc` |
| classic / Test I normal envelope | `8bed59407b8e5da6` | `8bed59407b8e5da6` | `d86c4cef594559fb` |
| classic / Test D noise only | `c473d3385b5767ba` | `c473d3385b5767ba` | `6fadc27660522c49` |
| classic / Test J silence | `81296f5b21ed7843` | `81296f5b21ed7843` | `81296f5b21ed7843` |
| src / 44100_silence | `9c30604f57c67643` | `9c30604f57c67643` | `9c30604f57c67643` |
| src / 44100_impulse | `77cb365a04153cd6` | `77cb365a04153cd6` | `2a701f23222f5ab6` |
| src / 44100_sine1k | `384838fbe0ae7880` | `384838fbe0ae7880` | `fe8480b0cf79c37e` |
| src / 44100_noise | `7bdfc09e387f584e` | `7bdfc09e387f584e` | `f0bfb679908b6f00` |
| src / 44100_transient | `aef5bc5dc8424320` | `aef5bc5dc8424320` | `13da2198939f382b` |
| src / 48000_silence | `571f74d802dc6b83` | `571f74d802dc6b83` | `571f74d802dc6b83` |
| src / 48000_impulse | `7e808dc5206ec172` | `7e808dc5206ec172` | `4fc2eb02cafdfe23` |
| src / 48000_sine1k | `91a94602740d03c7` | `91a94602740d03c7` | `6b006d5e9d35b593` |
| src / 48000_noise | `173cb1d55f3a6eb6` | `173cb1d55f3a6eb6` | `5b305d494916143c` |
| src / 48000_transient | `fa3eca2322710cdd` | `fa3eca2322710cdd` | `d3fa7c73222f9dd3` |
| src / 88200_silence | `4604fb4ba8dd1903` | `4604fb4ba8dd1903` | `4604fb4ba8dd1903` |
| src / 88200_impulse | `9cd8ed5cddc2eecb` | `9cd8ed5cddc2eecb` | `ddc3c4d2a6ea86ac` |
| src / 88200_sine1k | `33704ba92964b99a` | `33704ba92964b99a` | `133203557ecab650` |
| src / 88200_noise | `0be6614ccb40bb0b` | `0be6614ccb40bb0b` | `da06e8d23b77df02` |
| src / 88200_transient | `ca2ae2a966128a31` | `ca2ae2a966128a31` | `3c66426bc1951040` |
| src / 96000_silence | `4f9197d17adbd383` | `4f9197d17adbd383` | `4f9197d17adbd383` |
| src / 96000_impulse | `1ef2f1d127eee2b7` | `1ef2f1d127eee2b7` | `ce71183eb28ccb96` |
| src / 96000_sine1k | `cee808929d7a015c` | `cee808929d7a015c` | `0f96fa07ebad380f` |
| src / 96000_noise | `8cec30fdf443ef70` | `8cec30fdf443ef70` | `84e8578e8e4e1176` |
| src / 96000_transient | `0782d3ea6c5e70e7` | `0782d3ea6c5e70e7` | `a08da0479701bdcf` |
| src / 176400_silence | `4ecef083be81ee83` | `4ecef083be81ee83` | `4ecef083be81ee83` |
| src / 176400_impulse | `0ecd7a7279a32a35` | `0ecd7a7279a32a35` | `f4ccb55a076bcf79` |
| src / 176400_sine1k | `2694a697b0cf8229` | `2694a697b0cf8229` | `dfaab4202d3c5055` |
| src / 176400_noise | `214e98de2e28ef91` | `214e98de2e28ef91` | `990782f45766381b` |
| src / 176400_transient | `1aa35fb6f8abb09a` | `1aa35fb6f8abb09a` | `3187a7399ad8993e` |
| src / 192000_silence | `97cc35a2251aa383` | `97cc35a2251aa383` | `97cc35a2251aa383` |
| src / 192000_impulse | `50ca75d7ab7f1cca` | `50ca75d7ab7f1cca` | `1ab9619f9d9423f1` |
| src / 192000_sine1k | `efc0c2ee71bad520` | `efc0c2ee71bad520` | `42c01af30dc55076` |
| src / 192000_noise | `8b0a8d39e516d8d7` | `8b0a8d39e516d8d7` | `d28c5f6b23335e82` |
| src / 192000_transient | `2e5233ae6529729e` | `2e5233ae6529729e` | `162f0e809786ffd4` |
| integrated / off_default | `9259aab1c591727e` | `9259aab1c591727e` | `b3b33b801866dbac` |
| integrated / distortion_default | `8817d1113ae623f6` | `8817d1113ae623f6` | `0ce9cc9d3db24c0c` |
| integrated / crush_default | `8a31616a6fa6aab2` | `8a31616a6fa6aab2` | `4742b0df7b203420` |
| integrated / combPositive_default | `267920d638fd9335` | `267920d638fd9335` | `bc87a2a40db457ea` |
| integrated / combNegative_default | `b4073e2570f056b0` | `b4073e2570f056b0` | `11b337f8016400a6` |
| integrated / ringMod_default | `28a756a09db1f074` | `28a756a09db1f074` | `a31d4711f4cecac7` |
| integrated / delay_default | `400dc09a72426a7b` | `400dc09a72426a7b` | `84b9fac4b542955e` |
| integrated / delayFeedback_default | `400dc09a72426a7b` | `400dc09a72426a7b` | `84b9fac4b542955e` |
| integrated / delayDub_default | `400dc09a72426a7b` | `400dc09a72426a7b` | `84b9fac4b542955e` |
| integrated / crushDelayFeedback_default | `400dc09a72426a7b` | `400dc09a72426a7b` | `84b9fac4b542955e` |
| integrated / crushDelayDub_default | `400dc09a72426a7b` | `400dc09a72426a7b` | `84b9fac4b542955e` |
| integrated / delay16_default | `400dc09a72426a7b` | `400dc09a72426a7b` | `84b9fac4b542955e` |
| integrated / delay12_default | `400dc09a72426a7b` | `400dc09a72426a7b` | `84b9fac4b542955e` |
| integrated / delay8_default | `400dc09a72426a7b` | `400dc09a72426a7b` | `84b9fac4b542955e` |
| integrated / delay3_16_default | `400dc09a72426a7b` | `400dc09a72426a7b` | `84b9fac4b542955e` |
| integrated / looper_default | `400dc09a72426a7b` | `400dc09a72426a7b` | `84b9fac4b542955e` |
| integrated / pitch_default | `5673780a78b12c38` | `5673780a78b12c38` | `d5b97a3bd61cac01` |
| integrated / distortion_cv1min | `5fcd5a4fa71958f5` | `5fcd5a4fa71958f5` | `2bc5949f355fe384` |
| integrated / distortion_cv1max | `5af78ba07ed4cba8` | `5af78ba07ed4cba8` | `8c7303cef5128441` |
| integrated / delayFeedback_cv2max | `5dcc4a73a0c1ba86` | `5dcc4a73a0c1ba86` | `af0f54a12f6c9e81` |
| integrated / looper_replay | `a538dccc999e97db` | `a538dccc999e97db` | `7de403153fd34cce` |
| integrated / seq_ringmod | `be7fb0911be00383` | `be7fb0911be00383` | `be7fb0911be00383` |
| dual / DualRelative_Paper_Minus12 | `a5418f72030ca56c` | `a5418f72030ca56c` | `f6b162548fe3de09` |
| dual / DualRelative_Paper_Center64 | `567ef6fb95cdb472` | `567ef6fb95cdb472` | `109d055f10c008d3` |
| dual / DualRelative_Paper_Plus12 | `66ed4f4c07a50d83` | `66ed4f4c07a50d83` | `4d9b635f04c11c00` |
| dual / DualRelative_Eagle_Minus12 | `0e9265e82289808a` | `0e9265e82289808a` | `0bedfb035b4ee0b6` |
| dual / DualRelative_Eagle_Center64 | `d9dbe8c95525e5b8` | `d9dbe8c95525e5b8` | `916ff838398ce2da` |
| dual / DualRelative_Eagle_Plus12 | `ddc5f8a84b6c52a3` | `ddc5f8a84b6c52a3` | `103b21012a32de73` |
| dual / DualIndependent_Paper_Cut40_Res32 | `f666bfd056d076fc` | `f666bfd056d076fc` | `9dc39565ee5413bd` |
| dual / DualIndependent_Paper_Cut90_Res32 | `3acfa698d58aa88e` | `3acfa698d58aa88e` | `7f6ee86551feea60` |
| dual / DualIndependent_Paper_Cut90_Res63 | `3c42ee56a924fb6c` | `3c42ee56a924fb6c` | `3c6eb5fe8d0a948e` |
| dual / DualIndependent_Eagle_Cut40_Res32 | `811d9feadbc5c7d3` | `811d9feadbc5c7d3` | `4160e7f71d501196` |
| dual / DualIndependent_Eagle_Cut90_Res32 | `47b06b64de6c9b05` | `47b06b64de6c9b05` | `35219d8b116eaef2` |
| dual / DualIndependent_Eagle_Cut90_Res63 | `7e672b793567f751` | `7e672b793567f751` | `7e0e2b5212915cd6` |

Full qualification: **BLOCKED**. Independent Mac audio authority: **REVIEW_REQUIRED**. Next action: execute/retrieve the targeted captures and compare raw stages; change neither audio authority nor production behavior based on the original checksum failures.
