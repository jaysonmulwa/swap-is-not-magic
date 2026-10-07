"""Memory workloads for the swap experiments.

Runs inside a memory-limited container (see run_experiments.py). Stdlib only.
Each mode prints JSON lines. If the kernel kills the process, the last line
printed is the last thing that happened before death.

A "request" is 64 random page writes into a buffer. It stands in for a
service handling one request against data it keeps in memory.
"""
import json
import random
import resource
import sys
import time
from array import array

MB = 1024 * 1024
PAGE = 4096
PAGES_PER_REQUEST = 64
RING = 200_000  # ponytail: percentiles over the last 200k requests, enough for these runs


def emit(**kw):
    print(json.dumps(kw), flush=True)


def alloc(mb):
    # bytearray(n) can map lazy zero pages, so write one byte per page to make them real.
    buf = bytearray(mb * MB)
    for i in range(0, len(buf), PAGE):
        buf[i] = 1
    return buf


def usage():
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime, r.ru_majflt


def serve(buf, seconds, rnd):
    """Run requests against buf for `seconds`. Return throughput and latency stats."""
    npages = len(buf) // PAGE
    lat = array("Q", bytes(8 * RING))
    n = 0
    cpu0, flt0 = usage()
    start = time.perf_counter()
    end = start + seconds
    worst = 0
    while time.perf_counter() < end:
        t = time.perf_counter_ns()
        for _ in range(PAGES_PER_REQUEST):
            i = rnd.randrange(npages) * PAGE
            buf[i] = (buf[i] + 1) & 255
        d = time.perf_counter_ns() - t
        lat[n % RING] = d
        worst = max(worst, d)
        n += 1
    wall = time.perf_counter() - start
    cpu1, flt1 = usage()
    s = sorted(lat[: min(n, RING)])
    pct = lambda p: round(s[min(len(s) - 1, int(len(s) * p))] / 1000, 1) if s else None
    return {
        "requests": n,
        "rps": round(n / wall),
        "p50_us": pct(0.50),
        "p99_us": pct(0.99),
        "max_us": round(worst / 1000, 1),
        "major_faults": flt1 - flt0,
        "cpu_pct": round(100 * (cpu1 - cpu0) / wall),
    }


def mode_workingset(size_mb, seconds):
    """A buffer of size_mb, all of it hot: every page is equally likely to be used."""
    rnd = random.Random(42)
    t = time.perf_counter()
    buf = alloc(size_mb)
    alloc_s = time.perf_counter() - t
    serve(buf, 3, rnd)  # warm-up, not recorded: let the kernel settle what stays in RAM
    emit(mode="workingset", size_mb=size_mb, alloc_s=round(alloc_s, 2), **serve(buf, seconds, rnd))


def mode_cold(cold_mb, hot_mb, seconds):
    """cold_mb is written once and never read again. Requests only touch hot_mb."""
    rnd = random.Random(42)
    cold = alloc(cold_mb) if cold_mb else None
    hot = alloc(hot_mb)
    serve(hot, 3, rnd)
    emit(mode="cold", cold_mb=cold_mb, hot_mb=hot_mb, **serve(hot, seconds, rnd))
    del cold


def mode_spike(base_mb, spike_mb, after_s):
    """Steady base_mb working set. Then a brief extra spike_mb, held 2s and freed.
    Afterwards, report every second so the recovery curve is visible."""
    rnd = random.Random(42)
    base = alloc(base_mb)
    serve(base, 3, rnd)
    emit(phase="before", **serve(base, 5, rnd))
    t = time.perf_counter()
    spike = alloc(spike_mb)
    time.sleep(2)
    del spike
    emit(phase="spike", spike_s=round(time.perf_counter() - t, 2))
    for second in range(1, after_s + 1):
        emit(phase="after", second=second, **serve(base, 1, rnd))


def mode_leak(hot_mb, rate_mb, chunk_mb=4):
    """Serve requests on hot_mb while leaking rate_mb every second, until killed."""
    rnd = random.Random(42)
    hot = alloc(hot_mb)
    leaked = []
    t0 = time.perf_counter()
    while True:
        a = time.perf_counter()
        for _ in range(rate_mb // chunk_mb):
            leaked.append(alloc(chunk_mb))  # never read again, like a real leak
        alloc_ms = (time.perf_counter() - a) * 1000
        stats = serve(hot, max(0.1, 1 - (time.perf_counter() - a)), rnd)
        emit(t=round(time.perf_counter() - t0, 1), leaked_mb=len(leaked) * chunk_mb,
             alloc_ms=round(alloc_ms), **stats)


if __name__ == "__main__":
    mode, *args = sys.argv[1:]
    {"workingset": mode_workingset, "cold": mode_cold, "spike": mode_spike, "leak": mode_leak}[mode](
        *map(int, args)
    )
