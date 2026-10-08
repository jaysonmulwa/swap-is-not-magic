# swap-is-not-magic

These are the experiments behind [Why adding swap is not always the fix](https://medium.com/jaysonmulwa/why-adding-swap-is-not-always-the-fix-0a5a77fb0552), a post about when swap actually helps a machine that has run out of memory, and when it just turns a clean crash into a slow, quiet mess that nobody notices until a customer does.

The idea is simple enough. A small Python program pretends to be a service, keeping a buffer in memory and answering "requests" against it, and it runs inside a Docker container that is only allowed 256 MB of RAM. Each run gives that container a different amount of swap and a different kind of memory problem (a short spike, some memory that's never touched again, a working set that simply doesn't fit, or a leak), and then records how many requests per second it managed, how slow the slowest ones were, how many times it had to go to disk for a page, how busy the CPU was, and whether the kernel lost patience and killed it.

## What you need

You need Docker, and Docker needs to be able to give containers swap, which is less of a given than it sounds. On Windows and macOS, Docker Desktop runs everything inside its own small Linux VM, and that VM comes with swap of its own, so it works out of the box. On Linux, the host needs swap turned on and the kernel needs swap accounting enabled; if `docker info` prints `WARNING: No swap limit support`, Docker will quietly ignore the swap settings and every result will be wrong in a way that looks perfectly plausible, which is the worst kind of wrong.

You also need the `python:3.12-slim` image:

```bash
docker pull python:3.12-slim
```

and Python 3.8 or newer on the host to run the driver, which uses nothing outside the standard library.

## Running it

```bash
python run_experiments.py --repeats 3
```

That runs all 20 configurations three times over, which took about 30 minutes on the laptop the post was written on. It prints a line as each run finishes:

```
[0] spike      no swap                        exit=137 oom=True 13.4s
[0] spike      512 MB swap                    exit=0 oom=False 52.3s
```

Don't be alarmed by `exit=137 oom=True`. That's the kernel's out-of-memory killer ending the container, and for several of these configurations that is exactly the result we're looking for, not a bug in the script.

If you only care about one experiment, or want a quick single pass before committing half an hour to it, you can narrow things down:

```bash
python run_experiments.py --only workingset --repeats 1
```

where `--only` takes `spike`, `cold`, `workingset`, `moreswap` or `leak`.

## The experiments

| Name | What it does | Section of the post |
|---|---|---|
| `spike` | Holds a steady 150 MB, grabs 200 MB more for two seconds, lets it go, then watches the recovery every second for 40 s. | Layer 3 |
| `cold` | Writes 200 MB once and never reads it again, next to a busy 100 MB. | Layer 4 |
| `workingset` | One buffer where every page is equally busy, grown from 64 MB to 512 MB, with 1 GB of swap. | Layers 5 and 8 |
| `moreswap` | A busy 384 MB buffer with 512 MB and then 2 GB of swap, to see whether more swap helps. (It doesn't.) | Layer 6 |
| `leak` | Leaks 16 MB a second while serving from 64 MB, until the kernel kills it, with anywhere from no swap to 1 GB. | Layer 7 |

A "request", in all of these, is 64 writes, each one to a random 4 KB page somewhere in the buffer. It's a crude stand-in for a real service, but it has the one property that matters here, which is that every request touches memory the program actually cares about.

## What comes out

Everything lands in `results/`. The file you'll probably want first is `summary.md`, which has one table per experiment with the median across repeats, and is where every number in the post came from. Behind it sits `raw.jsonl`, with one line per run holding its configuration, exit code, whether it was OOM-killed, and every line the workload printed along the way, so you can check any summary number against the run that produced it. `environment.txt` records the host, the Docker version, and the kernel, CPU count and swappiness inside the VM, and `console.log` is just the progress lines.

You'll also find `raw-interrupted-run.jsonl` and `console-interrupted-run.log`. Those come from an earlier attempt, a day before, that got through one full repeat before the session running it ended, and they're kept because the post leans on them when it talks about how much the numbers moved from one day to the next. A new run won't touch them, but it will overwrite `raw.jsonl`, `summary.md` and `environment.txt`, so commit or copy those first if you want to compare.

## What to expect on your machine

Your absolute numbers won't match mine, and they shouldn't. They depend on the CPU, the disk under the swap, and even the laptop's power state; on the same machine, the baseline moved from about 10,000 to about 14,000 requests per second between two days. What should hold up is the shape of things: throughput falls off a cliff as the working set approaches the 256 MB limit, the runs without swap get killed in `spike`, `cold` and `leak`, and in `leak` each extra 256 MB of swap buys roughly another 16 seconds before the end. If your swap lives on something slower than an NVMe SSD, like a spinning disk or a network volume, I'd expect the cliff to be steeper, not gentler.

## What it does to your machine

Not much, by design. Each container is capped at 256 MB of RAM, so the rest of the system keeps its memory. The swap-heavy runs do write to the host's (or the Docker VM's) swap, up to about 1 GB during the largest leak run, and they keep the disk busy while they're at it, so it's not the moment to be compiling something big in another window. Every container is removed when its run finishes.

## Files

- [memlab.py](memlab.py) is the workload. It runs inside the container and prints a JSON line for everything it measures.
- [run_experiments.py](run_experiments.py) is the driver. It starts each container, collects what the workload printed, and writes the summary.
