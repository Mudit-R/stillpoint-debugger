# Engine and workbench

```
Local browser -> Python HTTP bridge -> C++ tracer -> ptrace -> child executable
                      |                    |
                 addr2line             ELF symbols
```

The tracer is a long-lived, single-threaded process. Every command and wait is
performed by the same tracer thread; Python's request threads serialize access
with a lock. JSON snapshots flow out through stdout, newline commands through
stdin. Child output goes into a temporary file instead of corrupting the
protocol. The engine reads it using `pread`, preserving the child's file offset.

## State

`idle -> running -> stopped -> running -> exited`. Launch replaces the previous
session; end kills and reaps the child. Inspection and breakpoint changes require
a stopped child. Continue waits up to 700 ms before returning `running`; polling
is nonblocking, allowing the workbench to pause a program that never completes.
`PTRACE_O_EXITKILL` terminates the tracee if the tracer disappears.

## Software breakpoints

Each breakpoint stores its address, original byte, and insertion state. Writes
modify a single byte in an aligned machine word, preserving adjacent breakpoints.
On an INT3 stop at a known breakpoint, the engine restores the original byte and
rewinds RIP by one byte. The next resume single-steps the restored instruction,
reinserts INT3, then continues unless a new stop needs attention. Deleting a
breakpoint while stopped on it still steps the restored instruction correctly.

## Signals

Instruction-step SIGTRAP and debugger-requested SIGSTOP are consumed. Other stop
signals are retained and delivered on resume, including SIGSEGV. A crash can be
inspected before the user resumes and allows its normal termination. The first
exec trap is consumed during launch. Attach and exec-after-launch transitions
are outside the supported lifecycle.

## Trace interpretation

Source line lookup invokes `addr2line` with an argument vector, never a shell.
The stack walker follows RBP under an increasing-address and maximum-distance
bound; it is not a DWARF unwinder. The stop history is a collection of captured
observations, not a recording of all execution or a reverse debugger.

The native ptrace interface is documented at
https://man7.org/linux/man-pages/man2/ptrace.2.html.
