"""Run every swap experiment in a memory-limited Docker container and save the results.

Usage:   python run_experiments.py [--repeats N] [--only EXPERIMENT]
Needs:   Docker, and the python:3.12-slim image (docker pull python:3.12-slim).
Writes:  results/raw.jsonl      every run, with every line the workload printed
         results/summary.md     medians across repeats, one table per experiment
         results/environment.txt

Every container gets 256 MB of RAM. Swap is set per run with --memory-swap,
which in Docker means RAM + swap. So --memory-swap=256m means no swap at all.
"""
import argparse
import json
import platform
import statistics
import subprocess
import time
import uuid
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "results"
IMAGE = "python:3.12-slim"
RAM_MB = 256

# (experiment, label, swap_mb, workload args)
RUNS = [
    ("spike", "no swap", 0, ["spike", 150, 200, 40]),
    ("spike", "512 MB swap", 512, ["spike", 150, 200, 40]),
    ("cold", "hot 100 MB only, no swap", 0, ["cold", 0, 100, 10]),
    ("cold", "+ cold 200 MB, no swap", 0, ["cold", 200, 100, 10]),
    ("cold", "+ cold 200 MB, 512 MB swap", 512, ["cold", 200, 100, 10]),
    *[("workingset", f"{mb} MB", 1024, ["workingset", mb, 10]) for mb in (64, 128, 192, 224, 256, 288, 320, 384, 512)],
    ("moreswap", "384 MB hot, 512 MB swap", 512, ["workingset", 384, 10]),
    ("moreswap", "384 MB hot, 2 GB swap", 2048, ["workingset", 384, 10]),
    *[("leak", f"{mb} MB swap", mb, ["leak", 64, 16]) for mb in (0, 256, 512, 1024)],
]


def sh(*cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def run_one(swap_mb, args):
    name = f"memlab-{uuid.uuid4().hex[:8]}"
    t = time.perf_counter()
    p = sh("docker", "run", "-i", "--name", name, f"--memory={RAM_MB}m", f"--memory-swap={RAM_MB + swap_mb}m",
           IMAGE, "python", "-u", "-", *map(str, args),
           input=(HERE / "memlab.py").read_text(), timeout=900)
    wall = time.perf_counter() - t
    oom, code = sh("docker", "inspect", "-f", "{{.State.OOMKilled}} {{.State.ExitCode}}", name).stdout.split()
    sh("docker", "rm", name)
    lines = [json.loads(l) for l in p.stdout.splitlines() if l.startswith("{")]
    return {"exit_code": int(code), "oom_killed": oom == "true", "wall_s": round(wall, 1), "lines": lines,
            "stderr_tail": p.stderr[-300:]}


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 1) if xs else "-"


def killed(rs):
    return f"{sum(r['oom_killed'] for r in rs)}/{len(rs)}"


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    return "\n".join(out + ["| " + " | ".join(map(str, r)) + " |" for r in rows])


def summarise(results):
    groups = {}
    for r in results:
        groups.setdefault(r["experiment"], {}).setdefault(r["label"], []).append(r)
    md = []

    def last(rs, key):
        return med([r["lines"][-1].get(key) for r in rs if r["lines"] and not r["oom_killed"]])

    def phase(rs, name, key):
        return med([l.get(key) for r in rs for l in r["lines"] if l.get("phase") == name])

    def after(rs, second, key="rps"):
        return med([l.get(key) for r in rs for l in r["lines"] if l.get("phase") == "after" and l["second"] == second])

    def recovered(r):
        # First second after the spike where throughput is back to 90% of before.
        before = next((l["rps"] for l in r["lines"] if l.get("phase") == "before"), None)
        return next((l["second"] for l in r["lines"] if l.get("phase") == "after" and l["rps"] >= 0.9 * before), None)

    if "spike" in groups:
        md += ["## spike: 150 MB steady, +200 MB for 2 s", table(
            ["config", "OOM-killed", "rps before", "spike took (s)", "rps 1s after", "rps 5s after",
             "rps 10s after", "rps 20s after", "back to 90% after (s)"],
            [[k, killed(rs), phase(rs, "before", "rps"), phase(rs, "spike", "spike_s"),
              after(rs, 1), after(rs, 5), after(rs, 10), after(rs, 20),
              med([recovered(r) for r in rs if not r["oom_killed"]])]
             for k, rs in groups["spike"].items()])]
    for exp, title in (("cold", "cold: idle memory next to a hot set"),
                       ("workingset", "workingset: everything hot, 256 MB RAM, 1 GB swap"),
                       ("moreswap", "moreswap: does more swap help a thrashing set?")):
        if exp in groups:
            md += [f"## {title}", table(
                ["config", "OOM-killed", "rps", "p50 (us)", "p99 (us)", "max (us)", "major faults", "CPU %"],
                [[k, killed(rs)] + [last(rs, f) for f in ("rps", "p50_us", "p99_us", "max_us", "major_faults", "cpu_pct")]
                 for k, rs in groups[exp].items()])]
    if "leak" in groups:
        md += ["## leak: 64 MB hot, leaking 16 MB/s", table(
            ["config", "OOM-killed", "survived (s)", "leaked at death (MB)", "rps first 3s", "rps last 3s",
             "p99 last 3s (us)", "alloc ms/s last 3s"],
            [[k, killed(rs), med([r["lines"][-1]["t"] for r in rs if r["lines"]]),
              med([r["lines"][-1]["leaked_mb"] for r in rs if r["lines"]]),
              med([l["rps"] for r in rs for l in r["lines"][:3]]),
              med([l["rps"] for r in rs for l in r["lines"][-3:]]),
              med([l["p99_us"] for r in rs for l in r["lines"][-3:]]),
              med([l["alloc_ms"] for r in rs for l in r["lines"][-3:]])]
             for k, rs in groups["leak"].items()])]
    return "\n\n".join(md) + "\n"


def environment():
    probe = "uname -r; nproc; free -m; cat /proc/sys/vm/swappiness"
    return "\n".join([
        f"host: {platform.platform()} {platform.processor()}",
        f"docker: {sh('docker', 'version', '--format', '{{.Server.Version}}').stdout.strip()}",
        f"image: {IMAGE}",
        f"container RAM limit: {RAM_MB} MB",
        "inside the VM (kernel, cpus, memory, swappiness):",
        sh("docker", "run", "--rm", IMAGE, "sh", "-c", probe).stdout,
    ])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--only")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    (OUT / "environment.txt").write_text(environment())
    results = []
    with open(OUT / "raw.jsonl", "w") as raw:
        for rep in range(a.repeats):
            for exp, label, swap_mb, args in RUNS:
                if a.only and exp != a.only:
                    continue
                r = {"experiment": exp, "label": label, "swap_mb": swap_mb, "args": args, "repeat": rep,
                     **run_one(swap_mb, args)}
                results.append(r)
                raw.write(json.dumps(r) + "\n")
                raw.flush()
                print(f"[{rep}] {exp:10} {label:30} exit={r['exit_code']} oom={r['oom_killed']} {r['wall_s']}s", flush=True)
    (OUT / "summary.md").write_text(summarise(results))
    print((OUT / "summary.md").read_text())


if __name__ == "__main__":
    main()
