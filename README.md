# Stillpoint

A native Linux debugger with a local execution workbench. The C++ engine controls
real child processes through `ptrace`; the browser displays observed process
state. GDB and LLDB are not used by the engine.

![Stillpoint paused at a real source location](docs/workbench.jpg)

## Run

Requires an x86-64 Linux host, or Docker Desktop with Linux containers on Windows.

```sh
docker build -t stillpoint .
docker run --rm --init --name stillpoint -p 127.0.0.1:8765:8765 --cap-add=SYS_PTRACE stillpoint
```

Open **http://127.0.0.1:8765**. Choose `ledger`, launch, enter `main` as a
breakpoint, and continue. Use instruction step to watch registers change. The
`crash` fixture demonstrates an inspectable SIGSEGV; `loop` demonstrates pausing
a running process. End the session before leaving the workbench.

Native build:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build -j2
python3 workbench/server.py
```

Build your own program into `build/` using
`g++ -g -O0 -fno-omit-frame-pointer -fno-pie -no-pie your.cpp -o build/your-program`.
The engine accepts an executable path through its CLI protocol; reload the workbench
to discover ELF executables in `build/`. Programs are launched without
arguments in this version; target stdin is disconnected from the debugger command
channel and reads EOF. Interactive terminal input is not supported yet.

## Implemented

- Launch, continue, instruction step, pause, end, and exit/signal reporting.
- Software breakpoints by function symbol or address, deletion, original-byte
  restoration, instruction-pointer correction and step-over/reinsertion.
- ELF64 function-symbol parsing with bounds validation.
- Twelve general/control register values and changed-value highlighting.
- Frame-pointer stack walking and an eight-word memory inspector accepting
  `rsp`, `rip`, a function symbol, or an explicit address.
- Source location and demangled stack names through GNU `addr2line`.
- Bounded source-line stepping in the workbench (step into, up to 128 instructions
  or two seconds; returns earlier at signals and breakpoints).
- Captured program output (up to 64 KiB), local stop history and JSON export.
- Real-process integration tests and Linux CI.
- Intel-syntax disassembly at the current instruction address via GNU objdump.
- Local AI investigation with cited stop evidence, hypothesis labels, stale-stop
  detection, and validation of evidence references.

## Local AI investigator

```sh
docker compose up -d --build
docker compose exec stillpoint-ai ollama pull qwen2.5-coder:1.5b
```

Open the workbench, launch `crash`, and continue to its SIGSEGV stop. In the
Investigator panel, ask what the stop suggests. The local model receives the
captured stop reason, registers, up to four stack frames, nearby example source,
instructions at RIP, and recent program output. The model does not receive the
whole repository. Model files stay in the ignored `.local/ollama/` directory.
The model server has no published host port in the Compose setup.

`STILLPOINT_AI_MODEL` selects an installed Ollama model; the example uses a small
CPU-friendly coding model for accessibility. Stronger models may reason better.
There is no bundled model, hosted API subscription, or silent rules-based fallback.
The AI integration follows [Ollama's chat API](https://docs.ollama.com/api/chat).

For a native installation, run Ollama separately and set
`STILLPOINT_AI_MODEL=qwen2.5-coder:1.5b` before starting the bridge. Its default
endpoint is `http://127.0.0.1:11434`. `STILLPOINT_AI_URL` accepts local endpoints
only, including Docker's `host.docker.internal` and Compose's `stillpoint-ai`.

Each report contains a capture fingerprint, evidence IDs, and proposed manual
checks. Unknown evidence IDs cause rejection. A valid citation does **not** prove
that the model's interpretation is correct. Nothing the model writes is executed;
continue, stepping and breakpoint changes remain explicit user actions. Program
output and source are untrusted inputs; prompt instructions and schema checks
are defense in depth, not a guarantee against misleading model output. Reports
are not persisted by the server. The workbench marks reports from earlier stops.

## Boundaries

This is an early, intentionally scoped debugger: **Linux x86-64, non-PIE,
single-process, single-threaded, unoptimized executables**. Frame pointers must
be retained for useful caller frames; a stop inside a function prologue/epilogue
can produce incomplete frames. Stripped executables lack function names. Shared
library source resolution is not implemented. Source display in the workbench
is limited to the included `examples/` tree. The ELF parser is ours; DWARF line
mapping and name demangling are delegated to binutils. There is no DWARF local
variable evaluation, source-level step-over/step-out, attach, watchpoint, reverse
execution, multi-client session isolation, or automated verification of AI hypotheses yet.

The workbench controls **one shared local session**. It executes native code;
it is not a sandbox for untrusted binaries. Keep its port bound to loopback.
It rejects foreign Host/Origin headers and does not accept arbitrary uploads.
The CLI does not have those browser launch restrictions.

## Test

```sh
docker run --rm --cap-add=SYS_PTRACE stillpoint python3 -m unittest discover -s tests -v
```

Tests use actual traced child processes. See [design notes](docs/architecture.md)
for state transitions, signal handling, and planned extensions.

## Next milestones

1. Source-line breakpoints and step-over/step-out; arbitrary project source roots.
2. DWARF local variable inspection with explicit unsupported-expression errors.
3. Thread lifecycle and thread-specific stop semantics.
4. Extend the AI investigator with user-approved, bounded experiments and an
   evaluation set of known failures. No diagnosis should be labelled verified
   without evidence.

No benchmark numbers or production-readiness guarantees are claimed.
