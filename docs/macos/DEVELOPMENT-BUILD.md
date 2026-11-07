# Isolated Intel-hosted development build

The prior preflight check annotation reported: "The job was not acquired by
Runner of type hosted even after multiple attempts". Both jobs had runner_id=0,
no runner name and no steps. This identifies hosted-runner acquisition failure;
its deeper cause (capacity, account restrictions or service behavior) is unknown.
Repository Actions is enabled; this is a public user-owned repository with supported
macos-15/macOS-15-intel labels. Billing APIs require a user scope unavailable to
the current token. No scope expansion or billing/account modification was attempted.
Node warnings occur after assignment, and do not explain a never-assigned job.

The original campaign was retried once without source changes. Its queued retry
was then cancelled at the owner's explicit request. The separate development
workflow performs current-SHA Intel preflight and universal AU/VST3 compilation
in one Intel-hosted job. It shares the exact existing harness, parser controls,
Xcode 16.4, JUCE 9.0.1, CMake 3.31.6, Ninja 1.11.1.4, deployment target 11.0,
x86_64/arm64 lipo checks, skin editor OFF and source/provenance protections.

It does not execute or bypass the full qualification gate and cannot claim native
ARM64 qualification or reference approval. The original macos-qualification.yml
and gate.py remain byte-identical. Binaries are UNQUALIFIED development artifacts,
with seven-day retention and existing temporary ad-hoc CI seals only. No Developer
ID signing, notarization, secrets, release, tag or automatic merge.

Node maintenance is separate: this workflow uses reviewed checkout v5,
setup-python v6.2.0 and upload-artifact v6.0.0 at immutable commit SHAs; their
upstream action.yml files declare node24. The original full workflow is retained
unchanged, including its older action pins. Its warnings are not attributed as
the cancellation cause.
