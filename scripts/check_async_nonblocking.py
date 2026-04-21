"""Live concurrency check against the running test backend.

Compares serial vs concurrent wall-clock for endpoints that B3 audit
moved onto a worker thread pool via asyncio.to_thread. If the event loop
were still being blocked by sync sqlite calls, concurrent and serial
wall-clock would be roughly equal.
"""

import asyncio
import statistics
import time

import httpx

BASE = "http://127.0.0.1:8766"
ENDPOINTS = [
    "/api/blacklist",
    "/api/blacklist/check?device_serial=test&customer_name=alice",
    "/api/media-actions/settings",
    "/api/followup/settings",
    "/api/followup/analytics",
]
N_PARALLEL = 32
N_REPEATS = 3


async def time_call(client: httpx.AsyncClient, url: str) -> float:
    t0 = time.perf_counter()
    r = await client.get(url, timeout=15.0)
    r.raise_for_status()
    return time.perf_counter() - t0


async def run_serial(client: httpx.AsyncClient, url: str, n: int) -> float:
    t0 = time.perf_counter()
    for _ in range(n):
        await time_call(client, url)
    return time.perf_counter() - t0


async def run_concurrent(client: httpx.AsyncClient, url: str, n: int) -> float:
    t0 = time.perf_counter()
    await asyncio.gather(*(time_call(client, url) for _ in range(n)))
    return time.perf_counter() - t0


async def main() -> None:
    async with httpx.AsyncClient() as client:
        await client.get(f"{BASE}/openapi.json", timeout=10.0)

        print(f"{'endpoint':50} {'serial(s)':>10} {'concurrent(s)':>14} {'speedup':>8}")
        print("-" * 88)
        all_speedups: list[float] = []
        for ep in ENDPOINTS:
            serial_times: list[float] = []
            concurrent_times: list[float] = []
            for _ in range(N_REPEATS):
                serial_times.append(await run_serial(client, f"{BASE}{ep}", N_PARALLEL))
                concurrent_times.append(
                    await run_concurrent(client, f"{BASE}{ep}", N_PARALLEL)
                )
            s = statistics.median(serial_times)
            c = statistics.median(concurrent_times)
            speedup = s / c if c > 0 else float("inf")
            all_speedups.append(speedup)
            print(f"{ep:50} {s:>10.3f} {c:>14.3f} {speedup:>7.2f}x")

        avg = statistics.mean(all_speedups)
        print()
        print(f"average speedup over {len(ENDPOINTS)} endpoints x {N_PARALLEL} reqs: {avg:.2f}x")
        if avg < 1.3:
            print("FAIL: event loop appears to still be serializing requests")
            raise SystemExit(2)
        print("PASS: concurrent execution faster than serial for SQLite-backed endpoints")


if __name__ == "__main__":
    asyncio.run(main())
