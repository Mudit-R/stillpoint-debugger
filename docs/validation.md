# Validation — 2026-10-31

Executed on Docker Desktop's Linux x86-64 engine, Ubuntu 24.04 container,
GNU C++ 13.3.0. The engine compiled with `-Wall -Wextra -Wpedantic -Werror`.

The integration suite uses live traced child processes, not mocks. Eleven tests
passed: seven original engine behaviors, explicit child reaping, source-line
stepping through the HTTP bridge, foreign-origin rejection, and launch-path
containment. Run `python3 -m unittest discover -s tests -v` inside the image.

Browser QA exercised launch, adding `main`, continuing to the breakpoint,
instruction stepping with RIP change, and stepping from ledger.cpp line 14 to
line 15. The screenshot in this directory shows the observed session.

This validates the included fixtures and supported platform. It does not establish
correctness for arbitrary optimized binaries, threads, subprocess trees, stripped
executables, shared library unwinding, or other architectures.
