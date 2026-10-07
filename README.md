# swap-is-not-magic

The experiments behind [article.md](article.md): when adding swap helps, and when it does not.

Every test runs a small Python "service" inside a Docker container capped at 256 MB of RAM, with a different amount of swap each time. It measures throughput, latency, major page faults and CPU use, and records whether the kernel killed the process.

## What you need

- Docker, with swap available to containers.
  - **Windows / macOS (Docker Desktop):** works out of the box. The Docker VM has its own swap.
  - **Linux:** the host needs swap enabled, and the kernel needs swap accounting. If `docker info` prints `WARNING: No swap limit support`, the swap settings are ignored and the results will be wrong.
- The `python:3.12-slim` image:

  ```bash
  docker pull python:3.12-slim
  ```

- Python 3.8 or newer on the host, to run the driver. It uses only the standard library.

## Reproduce

```bash
python run_experiments.py --repeats 3
```

This runs all 20 configurations three times, about 30 minutes on the laptop used for the article. Progress prints one line per run:

```
[0] spike      no swap                        exit=137 oom=True 13.4s
[0] spike      512 MB swap                    exit=0 oom=False 52.3s
```

`exit=137 oom=True` means the kernel's OOM killer ended the container. That is an expected result for some configurations, not a failure of the script.

To run one experiment only, or a quicker single pass:

```bash
python run_experiments.py --only workingset --repeats 1
```

`--only` takes `spike`, `cold`, `workingset`, `moreswap` or `leak`.

## The experiments

| Name | What it does | Article section |
|---|---|---|
| `spike` | 150 MB steady working set, plus 200 MB extra for 2 s. Tracks recovery every second for 40 s. | Layer 3 |
| `cold` | 200 MB written once and never read, next to a busy 100 MB. | Layer 4 |
| `workingset` | One buffer where every page is busy, from 64 MB to 512 MB, with 1 GB swap. | Layers 5 and 8 |
| `moreswap` | A 384 MB busy buffer with 512 MB and 2 GB of swap. | Layer 6 |
| `leak` | Leaks 16 MB a second while serving from 64 MB, until killed. Swap from 0 to 1 GB. | Layer 7 |

A "request" is 64 random writes, each on a random 4 KB page of the buffer.

## Output

Everything goes to `results/`:

| File | Contents |
|---|---|
| `summary.md` | One table per experiment, median across repeats. The article's tables come from here. |
| `raw.jsonl` | One line per run: its config, exit code, OOM flag and every line the workload printed. |
| `environment.txt` | Host, Docker version, kernel, CPU count and swappiness inside the VM. |
| `console.log` | The progress lines. |

`raw-interrupted-run.jsonl` and `console-interrupted-run.log` are from an earlier run, a day before, that stopped after one full repeat. The article cites them when it discusses run-to-run variance. A new run does not touch them.

A new run overwrites `raw.jsonl`, `summary.md` and `environment.txt`. Commit or copy them first if you want to compare.

## What to expect on your machine

Absolute numbers depend on CPU, disk and power state. On the same laptop, baselines moved from about 10,000 to about 14,000 requests per second between two days. Compare the ratios and shapes instead:

- The throughput cliff appears once the working set nears the 256 MB limit.
- Runs without swap are killed in `spike`, `cold` and `leak`.
- In `leak`, each 256 MB of swap adds about 16 s of life.

A slower disk under swap, such as a spinning drive or a network volume, should make the cliff deeper.

## Effect on the host

Each container is capped at 256 MB of RAM, so the rest of the machine keeps its memory. The swap-heavy runs do write to the host's or VM's swap, up to about 1 GB during the largest leak run, and they keep the disk busy while they run. Containers are removed after each run.

## Files

- [memlab.py](memlab.py) — the workload. Runs inside the container, prints JSON lines.
- [run_experiments.py](run_experiments.py) — the driver. Starts each container, collects results, writes the summary.
- [article.md](article.md) — the article. Tables are ASCII inside code blocks, so they paste into Medium as-is.
