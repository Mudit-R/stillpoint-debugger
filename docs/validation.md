# Validation — 2026-10-31

Executed on Docker Desktop's Linux x86-64 engine, Ubuntu 24.04 container,
GNU C++ 13.3.0. The engine compiled with `-Wall -Wextra -Wpedantic -Werror`.

The integration suite uses live traced child processes, not mocks. Eleven tests
passed: seven original engine behaviors, explicit child reaping, source-line
stepping through the HTTP bridge, foreign-origin rejection, and launch-path
containment. Run `python3 -m unittest discover -s tests -v` inside the image.

## Investigation and inspection extension

The expanded suite passes 19 tests. New real-engine checks cover arbitrary
memory inspection, invalid-address recovery, and adjacent breakpoint byte
preservation. The HTTP bridge also verifies disassembly at the current RIP.
AI unit tests use a controlled model adapter response: they verify evidence
construction, report parsing, citation rejection, missing configuration and
external-endpoint rejection. These adapter tests do not establish model quality.
The live model check is recorded separately below.

The source-breakpoint and argument-passing extension brought the automated suite
to 22 passing tests. These cover executable-line resolution, an explicit error
for an unmapped line, and arguments containing spaces and shell syntax passed
literally to the target. The debugger does not spawn a shell for target launch.

The incident-handoff extension and PIE/ASLR support raise the suite to 26 tests.
A five-target corpus (null read, PIE null read, null write, protected-page access,
and integer divide by zero) produces five downloadable Markdown reports with
kernel signal codes, source, stack, registers, instructions, output, and ELF build
IDs. The PIE fixture's source breakpoint and runtime disassembly resolve at its
relocated addresses. All five signatures are distinct; repeating the same null
read preserves its signature, while changing the build ID changes the signature.

The headless triage command adds three process-level checks: a crash writes a
build-aware report and returns `128 + signal`, a successful target returns its
own status without creating a crash report, and a timed-out target is stopped.
The full suite now passes 29 tests. GitHub Actions runs the command against the
crash fixture, checks its `SIGSEGV` report and status 139, then uploads the
handoff as a workflow artifact.

After rebuilding the local Compose service, a live API check launched the PIE
fixture under a non-zero ASLR load bias, stopped at `crash.cpp:10`, captured its
`SIGSEGV` at `crash.cpp:4`, and downloaded a handoff report containing that
build's ELF ID and RIP instructions.

Browser QA exercised launch, adding `main`, continuing to the breakpoint,
instruction stepping with RIP change, and stepping from ledger.cpp line 14 to
line 15. The screenshot in this directory shows the observed session.

This validates the included fixtures and supported platform. It does not establish
correctness for arbitrary optimized binaries, threads, subprocess trees, stripped
executables, shared library unwinding, or other architectures.

## Live local AI check

The Compose workbench ran Ollama 0.40.13 with `qwen2.5-coder:1.5b`. On the
included crash fixture, the adapter returned one unverified hypothesis in 15.74
seconds, citing the captured instruction pointer and RAX value. The debugger
independently captured `SIGSEGV / SEGV_MAPERR` at address zero, the faulting
instruction at `crash.cpp:4`, and the caller passing `nullptr` at line 10. This
demonstrates the local inference path and evidence-ID validation; it does not
establish general model accuracy or a measured reduction in human triage time.
