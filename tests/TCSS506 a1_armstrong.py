#!/usr/bin/env python3
"""
Armstrong Number Calculator using os.fork()

An Armstrong (narcissistic) number is one where the sum of each digit raised
to the power of the total number of digits equals the number itself.
    e.g.  153 = 1³ + 5³ + 3³
         9474 = 9⁴ + 4⁴ + 7⁴ + 4⁴

Usage
-----
Interactive (prompts for inputs):
    python3 "TCSS506 a1_armstrong.py"
    ./"TCSS506 a1_armstrong.py"

Command line arguments (BONUS task 7):
    ./"TCSS506 a1_armstrong.py" -n 10000000 -p 4
    -n   upper bound  (10 – 100,000,000)
    -p   processes    (1 – 100)
    If either flag is omitted the program prompts interactively for that value.

How os.fork() is used here
---------------------------
os.fork() duplicates the running process.  After the call, two processes
continue from the very next line.  They are told apart by the return value:
    - Parent receives the child's PID (a positive integer)
    - Child  receives 0

All pipes are created BEFORE any fork so that every child inherits every
pipe's file descriptors.  Each child closes every FD it does not own, does
its work, writes its results to its private pipe write-end, then exits.

The parent runs two separate loops:
    1. Fork loop  — spawns all children and saves their PIDs.
    2. Wait loop  — calls os.waitpid() for each saved PID.
Keeping the loops separate lets all children run in parallel instead of
sequentially (which would happen if we waited inside the fork loop).

Work distribution strategy
---------------------------
Rather than giving each process a contiguous block (which hands large,
slow-to-check numbers to just one process), the range is *striped*:

    process 0 checks:  start,   start+P,   start+2P, ...
    process 1 checks:  start+1, start+1+P, start+1+2P, ...
    ...
    process P-1 checks: start+P-1, start+P-1+P, ...

Each process therefore gets the same mix of small and large numbers,
keeping wall-clock time balanced across all workers.
"""

import argparse
import json
import os
import sys
import time


# ---------------------------------------------------------------------------
# Core math
# ---------------------------------------------------------------------------

# Pre-compute d^p for every digit d (0-9) and digit-count p (1-9).
# 10^9 = 1,000,000,000 > 100,000,000 so indices 1-9 cover the full range.
# Avoids calling the ** operator for every digit of every number checked.
_DIGIT_POWERS: list[list[int]] = [
    [d ** p for d in range(10)]
    for p in range(10)   # index 0 unused; 1-9 used
]


def is_armstrong(n: int) -> bool:
    """Return True if n is an Armstrong (narcissistic) number.

    Optimisations vs the naive approach:
      1. Pre-computed power table — no ** call per digit.
      2. Early exit — as soon as the running total exceeds n we stop;
         most non-Armstrong numbers fail quickly on their largest digit.
    """
    s = str(n)
    pw = _DIGIT_POWERS[len(s)]
    total = 0
    for ch in s:
        total += pw[int(ch)]
        if total > n:       # can never reach n — skip remaining digits
            return False
    return total == n


# ---------------------------------------------------------------------------
# Child worker — runs inside the forked process
# ---------------------------------------------------------------------------

def child_worker(
    process_index: int,
    start: int,
    max_num: int,
    num_processes: int,
    write_fd: int,
) -> None:
    """
    Find Armstrong numbers for this process's stripe and send them to the parent.

    Each child owns every (process_index)th number starting from
    start + process_index, stepping by num_processes.  This striped
    distribution ensures every worker handles a balanced mix of cheap
    (small) and expensive (large) numbers.

    Results are JSON-encoded and written to write_fd so the parent can
    read them after os.waitpid() returns.  The child then calls sys.exit(0)
    — crucial because without an explicit exit the child would fall through
    and execute the parent's remaining code.
    """
    found: list[int] = []

    # Stripe: this process checks every num_processes-th number.
    n = start + process_index
    while n <= max_num:
        if is_armstrong(n):
            found.append(n)
        n += num_processes

    # Only print when Armstrong numbers were actually found.
    if found:
        print(f"Child process PID: {os.getpid()} found {found}", flush=True)

    # Write results to the pipe so the parent can collect them.
    # json.dumps converts the list to a portable byte string.
    payload = json.dumps(found).encode()
    os.write(write_fd, payload)
    os.close(write_fd)   # closing signals EOF to the parent's os.read()

    # Always exit the child explicitly; never let it return to main().
    sys.exit(0)


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------

def parse_cli_args() -> tuple[int | None, int | None]:
    """
    Parse optional -n / -p command line flags (BONUS task 7).
    Returns (max_num, num_processes); either value is None if not supplied,
    which causes main() to fall back to an interactive prompt for that field.
    """
    parser = argparse.ArgumentParser(
        description="Calculate Armstrong numbers using os.fork().",
        add_help=True,
    )
    parser.add_argument(
        "-n",
        type=int,
        default=None,
        metavar="MAX",
        help="Upper bound for Armstrong search (10 – 100,000,000).",
    )
    parser.add_argument(
        "-p",
        type=int,
        default=None,
        metavar="PROCS",
        help="Number of worker processes to use (1 – 100).",
    )
    args = parser.parse_args()
    return args.n, args.p


def prompt_max_num() -> int:
    """Interactively prompt until a valid upper bound is entered."""
    while True:
        try:
            value = int(
                input(
                    "Please enter the maximum number to calculate Armstrong "
                    "numbers to (10 to 100,000,000): "
                )
            )
            if 10 <= value <= 100_000_000:
                return value
            print("Please enter a number between 10 and 100,000,000.")
        except ValueError:
            print("Please enter a valid integer.")


def prompt_num_processes() -> int:
    """Interactively prompt until a valid process count is entered."""
    while True:
        try:
            value = int(input("Please enter the number of processes to use: "))
            if 1 <= value <= 100:
                return value
            print("Please enter a number between 1 and 100.")
        except ValueError:
            print("Please enter a valid integer.")


# ---------------------------------------------------------------------------
# Entry point — parent process logic
# ---------------------------------------------------------------------------

def main() -> None:
    # os.fork() is a Unix system call; it is not available on Windows.
    if not hasattr(os, "fork"):
        print("Error: os.fork() is not available on this platform.")
        sys.exit(1)

    print("Welcome to the Armstrong number calculator.")

    # --- resolve inputs: CLI flags take priority; fall back to prompts ---
    cli_max, cli_procs = parse_cli_args()

    if cli_max is not None:
        if not (10 <= cli_max <= 100_000_000):
            print("Error: -n must be between 10 and 100,000,000.")
            sys.exit(1)
        max_num = cli_max
        # Echo the value so output matches interactive style.
        print(
            "Please enter the maximum number to calculate Armstrong "
            f"numbers to (10 to 100,000,000): {max_num}"
        )
    else:
        max_num = prompt_max_num()

    if cli_procs is not None:
        if not (1 <= cli_procs <= 100):
            print("Error: -p must be between 1 and 100.")
            sys.exit(1)
        num_processes = cli_procs
        print(f"Please enter the number of processes to use: {num_processes}")
    else:
        num_processes = prompt_num_processes()

    # --- timing starts AFTER all inputs are collected (task 2) ---
    start = 10
    total_numbers = max_num - start + 1
    numbers_per_process = total_numbers // num_processes
    print(f"Numbers per process:  {numbers_per_process}")

    # --- create pipes BEFORE forking ---
    # Each pipe is a (read_fd, write_fd) pair.  Creating them before any
    # os.fork() call means every child automatically inherits every pipe's
    # file descriptors — the child then closes the ones it does not own.
    pipes: list[tuple[int, int]] = [os.pipe() for _ in range(num_processes)]

    start_time = time.time()   # start timer after all input/setup
    child_pids: list[int] = []

    # -----------------------------------------------------------------------
    # FORK LOOP — spawn all children first, collect their PIDs
    # -----------------------------------------------------------------------
    for i in range(num_processes):
        # os.fork() returns twice:
        #   pid == 0  → we are the new child
        #   pid > 0   → we are the parent; pid is the child's PID
        pid = os.fork()

        if pid == 0:
            # ---- CHILD -------------------------------------------------
            # Close every pipe FD except our own write end.
            # Leaked read-ends would prevent the parent from seeing EOF;
            # leaked write-ends from other children are simply unnecessary.
            for j, (r, w) in enumerate(pipes):
                os.close(r)      # child never reads from any pipe
                if j != i:
                    os.close(w)  # not this child's write end

            # Do the work, write results, and exit.
            # child_worker() calls sys.exit(0) so we never return here.
            child_worker(i, start, max_num, num_processes, pipes[i][1])

        else:
            # ---- PARENT ------------------------------------------------
            # Close this child's write end so that when the child closes
            # its copy, the parent's os.read() will return an empty bytes
            # object (EOF) instead of blocking forever.
            os.close(pipes[i][1])
            child_pids.append(pid)

    # -----------------------------------------------------------------------
    # WAIT LOOP — wait for every child to finish
    # -----------------------------------------------------------------------
    # This is a separate loop so all children run in parallel.
    # os.waitpid(pid, 0) blocks until that specific child exits, then
    # returns (pid, exit_status).  We discard the return value here.
    for pid in child_pids:
        os.waitpid(pid, 0)

    # -----------------------------------------------------------------------
    # COLLECT RESULTS — read from every pipe read-end
    # -----------------------------------------------------------------------
    # All children have exited and closed their write-ends, so every pipe
    # will return EOF as soon as its buffered data is consumed.
    all_armstrong: list[int] = []
    for r_fd, _ in pipes:
        data = b""
        while True:
            chunk = os.read(r_fd, 65_536)
            if not chunk:        # empty bytes == EOF
                break
            data += chunk
        os.close(r_fd)
        if data:
            all_armstrong.extend(json.loads(data.decode()))

    all_armstrong.sort()

    elapsed_ms = int((time.time() - start_time) * 1000)
    print(f"It took {elapsed_ms} milliseconds to complete the task.")
    print(f"\nArmstrong numbers found: {', '.join(str(n) for n in all_armstrong)}")


if __name__ == "__main__":
    main()
