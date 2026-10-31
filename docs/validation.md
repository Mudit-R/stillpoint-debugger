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

The source-breakpoint and argument-passing extension brings the automated suite
to 22 passing tests. These cover executable-line resolution, an explicit error
for an unmapped line, and arguments containing spaces and shell syntax passed
literally to the target. The debugger does not spawn a shell for target launch.

Browser QA exercised launch, adding `main`, continuing to the breakpoint,
instruction stepping with RIP change, and stepping from ledger.cpp line 14 to
line 15. The screenshot in this directory shows the observed session.

This validates the included fixtures and supported platform. It does not establish
correctness for arbitrary optimized binaries, threads, subprocess trees, stripped
executables, shared library unwinding, or other architectures.

## Live local AI check

The Compose workbench ran Ollama 0.40.13 with `qwen2.5-coder:1.5b`. On the
included crash fixture, the adapter returned one hypothesis in 4.75 seconds,
labelled it unverified, and cited captured instructions and program output using
known evidence IDs. The debugger independently showed SIGSEGV at
`crash.cpp:4`, a zero RAX value, a load through `[rax]`, and the caller passing
`nullptr` at line 10. The model's cited evidence did not include the source excerpt
or RAX, so this run demonstrates the local integration and citation validation,
not that the model independently identified every relevant fact. One fixture and
one response do not establish model accuracy generally.
