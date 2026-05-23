#!/usr/bin/env python3
"""
Benchmark script for TCSS506 a1_armstrong.py  — Experimental Tasks 1-4

Runs the Armstrong calculator with 1-10 processes (n=10,000,000) and prints:
  • A runtime table in the terminal
  • A speedup table vs 1 process
  • A CSV block you can paste straight into Google Sheets / Excel

Usage (from the tests/ directory after chmod +x):
    python3 a1_benchmark.py                        # defaults: n=10M, p=1..10, 1 run
    python3 a1_benchmark.py --max 10000000 --max-procs 10 --runs 3
    python3 a1_benchmark.py --max 100000000 --max-procs 10   # bonus: 100M

Options:
    --max        Upper bound for Armstrong search  (default 10,000,000)
    --min-procs  Minimum process count to test     (default 1)
    --max-procs  Maximum process count to test     (default 10)
    --runs       Times to repeat each measurement  (default 1); averages results
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent / "TCSS506 a1_armstrong.py"
MS_RE  = re.compile(r"It took (\d+) milliseconds")


def run_once(n: int, p: int) -> int:
    """Run the calculator with -n N -p P and return elapsed milliseconds."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "-n", str(n), "-p", str(p)],
        capture_output=True,
        text=True,
    )
    match = MS_RE.search(proc.stdout)
    if not match:
        print("--- stdout ---", proc.stdout, sep="\n")
        print("--- stderr ---", proc.stderr, sep="\n")
        raise RuntimeError(f"Could not parse runtime (n={n}, p={p}).")
    return int(match.group(1))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark a1_armstrong.py across different process counts."
    )
    parser.add_argument(
        "--max", type=int, default=10_000_000, metavar="N",
        help="Upper bound for Armstrong search (default: 10,000,000).",
    )
    parser.add_argument(
        "--min-procs", type=int, default=1, metavar="P",
        help="Minimum number of processes to test (default: 1).",
    )
    parser.add_argument(
        "--max-procs", type=int, default=10, metavar="P",
        help="Maximum number of processes to test (default: 10).",
    )
    parser.add_argument(
        "--runs", type=int, default=1, metavar="R",
        help="Runs to average per process count (default: 1).",
    )
    args = parser.parse_args()

    print(
        f"\nBenchmarking a1_armstrong.py\n"
        f"  Upper bound : {args.max:,}\n"
        f"  Processes   : {args.min_procs} – {args.max_procs}\n"
        f"  Runs/config : {args.runs}\n"
    )

    results: list[tuple[int, float]] = []

    # -----------------------------------------------------------------------
    # Run and measure
    # -----------------------------------------------------------------------
    col_w = 14 if args.runs > 1 else 0
    header = f"{'Processes':>10}  {'Last run (ms)':>14}"
    if args.runs > 1:
        header += f"  {'Average (ms)':>14}"
    print(header)
    print("-" * len(header))

    for p in range(args.min_procs, args.max_procs + 1):
        times: list[int] = []
        for r in range(args.runs):
            print(f"  p={p}, run {r + 1}/{args.runs} …", end="\r", flush=True)
            times.append(run_once(args.max, p))

        avg = sum(times) / len(times)
        results.append((p, avg))

        row = f"{p:>10}  {times[-1]:>14}"
        if args.runs > 1:
            row += f"  {avg:>14.0f}"
        print(row + " " * 20)   # overwrite the progress line

    # -----------------------------------------------------------------------
    # Speedup table
    # -----------------------------------------------------------------------
    print()
    print(f"{'Processes':>10}  {'Avg (ms)':>12}  {'Speedup':>10}  {'Efficiency':>12}")
    print("-" * 50)
    base_ms = results[0][1]
    for p, avg in results:
        speedup    = base_ms / avg if avg > 0 else 0.0
        efficiency = speedup / p * 100        # % of perfect linear scaling
        print(f"{p:>10}  {avg:>12.0f}  {speedup:>10.2f}x  {efficiency:>11.1f}%")

    # -----------------------------------------------------------------------
    # CSV block — paste into Google Sheets / Excel
    # -----------------------------------------------------------------------
    print()
    print("=" * 50)
    print("CSV — paste into Google Sheets / Excel")
    print("=" * 50)
    print("Processes,Average runtime (ms),Speedup vs 1 process")
    for p, avg in results:
        speedup = base_ms / avg if avg > 0 else 0.0
        print(f"{p},{avg:.0f},{speedup:.2f}")
    print("=" * 50)


if __name__ == "__main__":
    main()
