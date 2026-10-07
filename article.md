# Why adding swap is not always the fix

Your service runs out of memory and gets killed. Someone says: add swap. You add swap, and the crashes stop.

A week later the service is still alive. It just takes seconds to answer a request that used to take microseconds. Nobody gets paged, because nothing crashed.

Swap did exactly what it was asked to do. It was the wrong thing to ask for. This post shows, with measurements, when swap is the right fix and when it only moves the problem somewhere quieter.

## The answer, first

Swap does not add memory. It adds a slow overflow area on disk.

That is useful when the extra memory is needed only briefly, or is not being used at all. It is harmful when the extra memory is being used all the time.

In my tests, a container with 256 MB of RAM handled about 14,000 requests per second. When its data grew past what RAM could hold, swap kept it alive — at 109 requests per second. About 130 times slower. Giving it four times more swap changed nothing.

A memory leak was worse in a different way. Swap did not stop the crash. It delayed it, in a straight line: every 256 MB of swap bought 16 more seconds. And while it waited, the service looked healthy.

That is the whole story. The rest of this post builds it up, layer by layer.

**What is measured and what is not.** The spike, idle-memory, thrashing, swap-size and leak results are measured, three runs each, on one laptop. The section on other platforms, and the fixes at the end, are background knowledge. They were not run here. The maths section fits a simple model to the measured data, and says which values are fitted.

## When swap helps, and when it does not

This is the table I wish I had before I reached for swap. Each row is tested in a layer below.

```
+-----------------------------+--------+-----------------------------+
| Situation                   | Swap?  | What I measured             |
+-----------------------------+--------+-----------------------------+
| Short spike above RAM       | Helps  | Survived. No swap: killed   |
| Idle memory                 | Helps  | Full speed. No swap: killed |
| Working set bigger than RAM | No     | Alive, but ~130x slower     |
| Same, with 4x more swap     | No     | No improvement              |
| Memory leak                 | Delays | +16 s of life per 256 MB    |
| Latency-sensitive service   | No     | p99 0.16 ms -> 18.5 ms      |
+-----------------------------+--------+-----------------------------+
```

And what to do about each:

```
+--------------------------------+------------------------------+
| Situation                      | Right fix                    |
+--------------------------------+------------------------------+
| Short spike above RAM          | Swap, sized for the spike    |
| Idle memory                    | Swap                         |
| Working set bigger than RAM    | More RAM, or use less memory |
| Same, with 4x more swap        | Same as above                |
| Memory leak                    | Fix the leak                 |
| Latency-sensitive service      | More RAM, memory limits      |
+--------------------------------+------------------------------+
```

The pattern is one question: **is the memory that does not fit actually being used?** If not, swap is cheap and helpful. If yes, swap turns a crash into a slowdown, and a slowdown can be worse.

## Layer 1: RAM, pages and swap

The operating system does not manage memory byte by byte. It manages it in pages — 4 KB chunks.

When RAM is full and a program asks for more, the kernel has three choices:

1. Drop a page it can re-read later, like part of a cached file.
2. Write a page out to swap, and reuse the RAM.
3. Kill a process. On Linux this is the OOM killer — the out-of-memory killer.

Without swap, choice 2 does not exist. Memory a program allocated cannot be dropped, so the kernel goes straight to killing.

With swap, the page goes to disk. If the program touches that page again, the kernel must read it back. That is called a **major page fault**. The program stops and waits for the disk while it happens.

This is the trade. RAM answers in about 100 nanoseconds. My swap cost roughly a quarter of a millisecond per fault — about 2,500 times slower. A few faults are invisible. Thousands per second are not.

That quarter of a millisecond is worked out, not timed directly. In the 384 MB run in Layer 5, the process waited about 8.1 of its 10 seconds, across 35,915 major faults. That is about 0.23 ms per fault.

## Layer 2: The test bench

I wanted a machine with very little RAM, so the effects show up quickly. A Docker container with a memory limit does that without touching the rest of the laptop.

Every test ran in a container with exactly 256 MB of RAM. Swap was set per test.

Docker's flag for this is easy to misread. `--memory-swap` is not the swap size. It is RAM plus swap.

```
+-----------------------------------+--------+--------+
| Flags                             |    RAM |   Swap |
+-----------------------------------+--------+--------+
| --memory=256m --memory-swap=256m  | 256 MB |   none |
| --memory=256m --memory-swap=768m  | 256 MB | 512 MB |
| --memory=256m --memory-swap=1280m | 256 MB |   1 GB |
+-----------------------------------+--------+--------+
```

Inside the container, a small Python script plays the part of a service. It keeps a buffer in memory. A **request** is 64 random writes into that buffer, each on a random page. It reports requests per second, latency percentiles, major page faults, and how busy the CPU was.

One detail about where the swap lives. On Windows, Docker runs inside WSL2 — a lightweight Linux virtual machine. The swap is a 4 GB virtual disk file inside that VM, and that file sits on the laptop's NVMe SSD. So this is close to the best case for swap. A spinning disk, or a cloud volume with limited IOPS, would be slower.

```
+---------------+--------------------------------------+
| What          | Value                                |
+---------------+--------------------------------------+
| Laptop        | Intel i9-13905H, 32 GB RAM, NVMe SSD |
| Kernel        | 5.15.153.1-microsoft-standard-WSL2   |
| Docker        | 28.3.0, image python:3.12-slim       |
| swappiness    | 60 (the default)                     |
| Container RAM | 256 MB                               |
+---------------+--------------------------------------+
```

Each configuration ran three times. The tables show the median.

One caution about absolute numbers. An earlier run, a day before, was interrupted after one full pass. Its baseline was about 10,000 requests per second, not 14,000. A laptop's speed moves with power state and heat. The shapes matched closely. The cliff sat in the same place, the same runs were killed, and the leak survival times agreed to within half a second. Read the ratios, not the raw numbers.

## Layer 3: A short spike — where swap helps

Start with the case swap was made for.

The service holds 150 MB of data and serves requests from it. Then, for about two seconds, it needs 200 MB more — think of a big report, an import, a burst of uploads. Then it frees it. 150 + 200 is well over 256.

```
+----------------------+----------------+------------------+
| Moment               |        No swap |      512 MB swap |
+----------------------+----------------+------------------+
| Outcome              | killed, 3 of 3 | survived, 3 of 3 |
| rps before the spike |         15,294 |           17,054 |
| rps 1 s after        |              - |               92 |
| rps 5 s after        |              - |              286 |
| rps 10 s after       |              - |           16,169 |
| rps 20 s after       |              - |           15,787 |
+----------------------+----------------+------------------+
```

Without swap, the kernel killed the process every time. All 150 MB of state, gone, because of a two-second spike.

With swap, it survived. That is a real win.

But look at the row. The spike lasted 2.4 seconds. The service then crawled at under 2% of its normal speed, and only got back to 90% after **9 seconds**.

Why? To make room for the spike, the kernel pushed most of the 150 MB of normal data out to swap. When the spike ended, that data had to come back. It came back one page fault at a time, as each request happened to touch it.

The lesson: swap absorbs a spike, but you pay for it after the spike ends. The hangover was nearly four times longer than the spike.

## Layer 4: Idle memory — where swap helps quietly

The second good case is memory that a program allocates and then never uses again. Startup caches, a loaded-but-unused library, a data structure built once.

The test: write 200 MB once and never touch it again. Then serve requests from a separate 100 MB. 300 MB in total, 256 MB of RAM.

```
+----------------------------+------------+---------+--------+
| Config                     |        rps |     p99 | Faults |
+----------------------------+------------+---------+--------+
| 100 MB hot, no swap        |     15,599 | 0.16 ms |      0 |
| + 200 MB cold, no swap     | killed 3/3 |       - |      - |
| + 200 MB cold, 512 MB swap |     15,613 | 0.15 ms |      0 |
+----------------------------+------------+---------+--------+
```

Without swap, that idle 200 MB was enough to get the process killed.

With swap, the kernel moved the idle pages to disk and kept the busy ones in RAM. The service ran at the same speed as the baseline, with **zero** major faults during the measurement. Nothing it was using ever had to come back from disk.

This is swap at its best. It quietly frees RAM from memory nobody is using. Most of the time you never notice it working.

## Layer 5: A working set larger than RAM — thrashing

Now change one thing. Instead of a small busy part and a large idle part, make all of it busy. Every page is equally likely to be touched by the next request.

The memory a program is actively using is called its **working set**. I grew it step by step, with 256 MB of RAM and 1 GB of swap.

"Faults" is major page faults during the 10-second measurement. "CPU" is how busy one core was.

```
+-------------+--------+---------+---------+--------+------+
| Working set |    rps |     p50 |     p99 | Faults |  CPU |
+-------------+--------+---------+---------+--------+------+
|       64 MB | 16,622 | 0.05 ms | 0.13 ms |      0 | 100% |
|      128 MB | 13,828 | 0.06 ms | 0.17 ms |      0 | 101% |
|      192 MB | 14,408 | 0.06 ms | 0.16 ms |      0 | 100% |
|      224 MB | 13,870 | 0.07 ms | 0.16 ms |      0 | 101% |
|      256 MB |  4,016 | 0.10 ms |  1.3 ms | 18,625 |  52% |
|      288 MB |    396 |  2.0 ms | 10.4 ms | 31,212 |  21% |
|      320 MB |    285 |  3.2 ms | 10.7 ms | 38,604 |  22% |
|      384 MB |    164 |  5.7 ms | 13.9 ms | 35,915 |  19% |
|      512 MB |    109 |  8.5 ms | 18.5 ms | 35,478 |  21% |
+-------------+--------+---------+---------+--------+------+
```

This is not a slope. It is a cliff.

Up to 224 MB, the service ran at full speed. At 256 MB — the moment the working set plus Python itself no longer fit — throughput fell by 71%. At 288 MB, just 64 MB over the line, it was 35 times slower. At 512 MB, about 130 times slower.

The 64 MB row is a little faster than the rest. A smaller buffer is friendlier to the CPU's caches. It has nothing to do with swap — it had zero major faults.

Nothing crashed. Every run exited cleanly. A health check would have passed every time.

This is **thrashing**. The kernel writes page A to swap to make room for page B. The next request needs page A. So it writes page B out to bring page A back. Round and round. The machine spends its time moving pages, not doing work.

The last column is the tell. A healthy run kept one CPU core fully busy, about 100%. A thrashing run had it busy only about 20% of the time. The other 80% the process was waiting on the disk.

That is worth remembering, because it is backwards from what most people expect. **A thrashing machine looks idle.** CPU is low, nothing is erroring, and everything is slow. If you only watch CPU, you will look in the wrong place.

## Layer 6: More swap does not fix thrashing

The natural reaction to the table above is: maybe it needs more swap. So I tested that directly. Same 384 MB working set, same 256 MB of RAM, different amounts of swap.

```
+--------+-----+--------+---------+--------+
|   Swap | rps |    p50 |     p99 | Faults |
+--------+-----+--------+---------+--------+
| 512 MB | 173 | 5.2 ms | 17.4 ms | 37,991 |
|   1 GB | 164 | 5.7 ms | 13.9 ms | 35,915 |
|   2 GB | 153 | 5.9 ms | 16.3 ms | 33,573 |
+--------+-----+--------+---------+--------+
```

No improvement. Four times more swap, and if anything slightly fewer requests — though a gap that small is within noise.

This makes sense once you see what limits it. The problem is not that swap is too small. 512 MB was already enough to hold everything. The problem is that the data has to keep moving between RAM and disk, and the disk is slow. A bigger disk area does not make the disk faster.

More swap only gives a thrashing machine more room to thrash in.

## Layer 7: A memory leak — swap buys time, and hides the bug

A memory leak is memory a program keeps allocating and never frees. It is the most common reason a service slowly runs out of memory. It is also the most common reason someone adds swap.

The test: serve requests from a 64 MB working set, while leaking 16 MB every second. Run until the kernel kills it.

```
+--------+--------+----------+-----------+---------+---------+
|   Swap |  Lived |   Leaked | rps start | rps end | p99 end |
+--------+--------+----------+-----------+---------+---------+
|   none | 11.1 s |   176 MB |    16,101 |  17,568 | 0.11 ms |
| 256 MB | 27.4 s |   432 MB |    15,211 |  16,949 | 0.13 ms |
| 512 MB | 43.4 s |   688 MB |    14,704 |  16,353 | 0.13 ms |
|   1 GB | 75.7 s | 1,200 MB |    15,962 |  17,462 | 0.12 ms |
+--------+--------+----------+-----------+---------+---------+
```

"Start" is the first 3 seconds, "end" the last 3 before death.

Every single run died. Swap never stopped the crash.

What swap did was buy time, and the arithmetic is exact. Each 256 MB of swap added 16 seconds of life. 256 MB divided by 16 MB per second is 16 seconds. The swap was simply filled, at the rate of the leak, and then the process was killed anyway.

On this test bench that is seconds. On a real service leaking 50 MB an hour, 4 GB of swap is about three and a half days. That sounds like a fix. It is a countdown with a longer display.

The second finding surprised me more. I expected the service to get very slow as it filled swap. It did not. In every configuration, throughput in the last three seconds before death was as high as at the start. The p99 never left about 0.1 ms.

The only sign was in the allocations themselves. Leaking 16 MB took about 8 ms a second without swap, and 25–28 ms with it, because the kernel had to write old pages out first. That is a number almost nobody graphs.

The reason is in Layer 4. Leaked memory is, by definition, never used again. It is idle memory. The kernel moves it to swap, the working set stays in RAM, and the service runs fine — right up to the moment it is killed.

So swap does not just delay a leak. It hides it. The service looks healthy, the memory graph looks fine because RAM is not full, and the leak grows in a place nobody is watching.

## Layer 8: Why latency-sensitive services hate swap

Throughput is one number. Most users feel the slow requests, not the average. That is what the p99 measures — the latency that 1 in 100 requests is slower than.

From the Layer 5 runs:

```
+---------------+-------------+------------------------+
|   Working set | p99 latency | Slowest single request |
+---------------+-------------+------------------------+
| 224 MB (fits) |     0.16 ms |                 5.0 ms |
|        256 MB |      1.3 ms |                20.9 ms |
|        512 MB |     18.5 ms |                58.4 ms |
+---------------+-------------+------------------------+
```

As soon as the working set crossed RAM, the p99 rose eightfold. At 512 MB it was about 115 times worse.

For a database, a cache like Redis, or anything with a timeout, that is the failure. A request that takes 18 ms instead of 0.16 ms is a timeout somewhere upstream. Retries pile on top of a machine that is already stuck waiting on its disk.

This is why databases and caches are usually told to avoid swap entirely. They would rather know they are out of memory than quietly get slow.

## What I nearly concluded instead

Wrong readings are cheap if you test them. Three of mine did not survive.

**"Swap broke the service after the spike."** My first spike test measured only five seconds after the spike. Throughput stayed at about 145 requests per second the whole time. It looked permanent. Extending the window to 40 seconds showed recovery at about 9 seconds. The swap-in was slow, not stuck.

**"Idle memory in swap costs about 8%."** The interrupted first run showed the idle-memory case at 92% of baseline. Three later runs showed 15,613 against 15,599 — no cost at all. One run is an anecdote.

**"A leaking service gets slow before it dies."** It did not, as Layer 7 showed. The leak was cold memory, so swap absorbed it well. That is worse news, not better: there is no slowdown to warn you.

## Does this happen outside Docker and WSL2?

Yes. Docker and WSL2 are where I measured it. They are not the cause.

The behaviour needs only two things: a working set larger than RAM, and somewhere to swap to. Background knowledge, not measured here:

- **Bare-metal Linux** behaves the same way. The kernel's page reclaim is the same code.
- **Kubernetes** long refused to start with swap enabled on a node, to keep memory limits predictable. Newer versions allow it, but it is opt-in.
- **Cloud VMs** often have swap on network-attached disks with limited IOPS. Every major fault becomes a network round trip. Thrashing there is worse than on my NVMe SSD.
- **Windows and macOS** use a page file and compressed memory. The words differ, the shape of the cliff does not.

What I measured is one laptop, with a fast SSD under the swap. On slower storage I would expect the cliff to be deeper, not shallower.

## The maths behind the cliff

The cliff in Layer 5 looks dramatic. It turns out to be simple arithmetic.

There is a whole field for this. The [External Memory](https://en.algorithmica.org/hpc/external-memory/) chapter of Algorithmica's *Algorithms for Modern Hardware* describes the external memory model. In it, the only thing that costs anything is moving a block between a small fast memory and a large slow one. Work on data already in fast memory is treated as free.

My test bench is that model, almost exactly:

```
+---------------------+----------------------+
| In the model        | In these tests       |
+---------------------+----------------------+
| Fast memory, size M | The 256 MB RAM limit |
| Slow memory         | Swap                 |
| Block, size B       | A 4 KB page          |
| One block transfer  | One major page fault |
+---------------------+----------------------+
```

My service picks pages uniformly at random. So the chance a page is already in RAM is just the share of the working set that fits:

```
hit chance          = M / W
misses per request  = 64 x (1 - M / W)
time per request    = t0 + misses per request x t_fault
```

W is the working set. t0 is the time per request when everything fits: 72 µs, from the 224 MB row. t_fault is the cost of one fault.

Two values here are fitted from the data, not measured directly. M comes out at about 250 MB — the RAM left for the buffer once Python and the container take their share. t_fault comes out at about 270 µs. With those two, the model predicts the rest. "Faults" here is faults per request.

```
+--------+-------------+--------------+----------+-----------+
|    Set | Faults real | Faults model | rps real | rps model |
+--------+-------------+--------------+----------+-----------+
| 256 MB |         0.5 |          1.5 |    4,016 |     2,096 |
| 288 MB |         7.9 |          8.4 |      396 |       425 |
| 320 MB |        13.5 |         14.0 |      285 |       260 |
| 384 MB |        21.9 |         22.3 |      164 |       164 |
| 512 MB |        32.5 |         32.8 |      109 |       112 |
+--------+-------------+--------------+----------+-----------+
```

From 288 MB up, the model lands within about 10%. At 256 MB, right on the edge, it is off by half. The kernel kept more in RAM than a simple model allows.

The fault cost is also a second opinion on Layer 1. There I got 0.23 ms per fault from waiting time. Here the fit gives 0.27 ms. Two different routes, nearly the same answer.

**Why a cliff, not a slope?** Misses grow in a straight line with the working set. But a page write that hits RAM costs about 1 µs in my Python service. One that misses costs about 270 µs. So one miss costs as much as roughly 250 hits.

At 288 MB, only about 1 in 8 page writes missed. That alone made the service 35 times slower. You do not need to miss often. You only need to miss at all.

**Which page goes to swap?** That is the eviction policy. The same book's [Eviction Policies](https://en.algorithmica.org/hpc/external-memory/policies/) page covers a result by Sleator and Tarjan ("Amortized efficiency of list update and paging rules", *Communications of the ACM*, 1985):

```
LRU(M) <= 2 x OPT(M/2)
```

LRU evicts the least recently used block. OPT is a perfect policy that knows the future. In words: LRU with M memory makes at most twice the misses of a perfect policy with half the memory. Linux uses an approximation of LRU — on this kernel, an "active" and an "inactive" list.

Three results in this post follow from that policy:

- **Idle memory and leaks had zero faults** (Layers 4 and 7). A page nobody reads is always the least recently used. So it is always the first to go to swap.
- **The spike hangover** (Layer 3). The spike's pages were newer, so the steady 150 MB was evicted instead. 150 + 200 − 250 is about 100 MB pushed out, or 25,600 pages. At 270 µs each, that is about 7 seconds of faults to bring back. I measured about 9 seconds to get back to 90%. A rough check, not a precise one.
- **Random access is not the worst case.** The theorem's worst case is a loop that scans slightly more blocks than fit, in order. LRU then misses on every access, 100%. My random access missed about half the time at 512 MB. A service that scans a table just bigger than RAM, in order, would thrash harder than anything in this post.

## Open questions

These are gaps in the evidence. None changes the conclusion.

**Why was the whole machine 40% faster on the second day?** Baselines went from about 10,000 to about 14,000 requests per second. Power plan, heat, or other load on the laptop are all candidates. I did not control for them. The ratios held, so the conclusions do.

**What happens with a leak that is not cold?** My leak was never read again. A leak that is still read now and then — a cache with no eviction, say — would behave more like Layer 5 than Layer 7. I did not test it.

**Would zram change the picture?** zram is swap that lives in compressed RAM instead of on disk. It makes faults much cheaper. It would likely soften the cliff in Layer 5. I did not test it.

**How bad is an in-order scan?** The maths section predicts 100% misses for a loop over slightly more than RAM. I did not measure it.

**Where exactly does the cliff start?** Between 224 MB and 256 MB of working set, inside 256 MB of RAM. Python and the container take some memory too. A finer sweep would place it more precisely.

## What to do instead

Everything above this line is measured. Everything below it is proposed, and was not run as part of these tests.

**1. Find out which row you are in first.** Swap that is used but quiet is fine. Swap that is constantly moving is thrashing. On Linux, watch the `si` and `so` columns (swap in, swap out):

```bash
vmstat 1
```

Steady non-zero numbers mean the working set does not fit. Memory pressure is also reported directly in `/proc/pressure/memory`, on kernels since 4.20. In a container, `docker stats` shows memory against the limit.

**2. Keep a small swap.** 1–4 GB is a sensible default for a general machine. It absorbs spikes and idle memory, which are the two rows where swap helps. It is too small to hide a leak for days.

**3. If the working set does not fit, fix the fit.** Add RAM, move to a bigger machine, or make the program use less memory. Swap cannot help here, at any size. Layer 6 showed that.

**4. If it is a leak, fix the leak.** Track memory over time, not just at a moment. A process whose memory only ever goes up is leaking, with or without swap.

**5. For latency-sensitive services, set memory limits and alert before the limit.** A clean OOM kill and a restart is often better than ten minutes of 18 ms requests. Tools like `systemd-oomd` and `earlyoom` act on memory pressure, before the machine starts thrashing.

**Do not turn swap off as a reflex either.** Layers 3 and 4 showed two cases where swap was the difference between surviving and being killed. Swap is a good tool. It is just not a memory upgrade.

## What to take away

**Swap is overflow, not memory.** It helps when the overflow is brief or unused. It hurts when the overflow is in use.

**Thrashing is a cliff, not a slope.** 64 MB over the line cost 97% of throughput.

**A thrashing machine looks idle.** CPU dropped to about 20%. Watch swap activity and memory pressure, not CPU.

**More swap does not fix thrashing.** Four times the swap, the same speed.

**Swap hides leaks.** It delays the crash in a straight line and removes the slowdown that would have warned you.

The question to ask is never "how much swap?" It is "is the memory that does not fit actually being used?"

## Reproduce it

The scripts are in the same folder as this post. They need Docker and the `python:3.12-slim` image.

```bash
python run_experiments.py --repeats 3
```

It runs every test above, three times, in about 30 minutes. Raw output goes to `results/raw.jsonl`, and the tables to `results/summary.md`. Each container is capped at 256 MB of RAM, so the rest of the machine is not affected.

## Glossary

**cgroup** — A Linux feature that limits how much CPU, memory and other resources a group of processes can use. Docker memory limits are built on it.

**Eviction policy** — The rule that decides which block leaves fast memory when space runs out.

**External memory model** — A cost model that counts only block transfers between a small fast memory and a large slow one.

**LRU** — Least recently used. An eviction policy that removes the block nobody has touched for the longest time. Linux approximates it.

**Major page fault** — A program touched a page that is not in RAM, so the kernel has to read it from disk. The program waits.

**Memory leak** — Memory a program keeps allocating and never frees.

**OOM killer** — The Linux out-of-memory killer. When memory runs out, it picks a process and ends it.

**p50, p99** — Percentile latencies. p99 is the time that 1 in 100 requests is slower than.

**Page** — The unit the kernel manages memory in. 4 KB on most machines.

**Page cache** — RAM the kernel uses to hold recently read files. It can be dropped and re-read, unlike memory a program allocated.

**PSI** — Pressure Stall Information. A Linux report of how much time tasks spend waiting for memory, CPU or IO. Found in `/proc/pressure/`.

**rps** — Requests per second.

**Swap** — Disk space used as overflow when RAM is full.

**swappiness** — A Linux setting from 0 to 200 that controls how willing the kernel is to swap. Default 60.

**Thrashing** — When a system spends most of its time moving pages between RAM and swap, and almost none doing real work.

**Working set** — The memory a program is actively using right now. Not everything it has allocated.

**WSL2** — Windows Subsystem for Linux, version 2. A lightweight Linux virtual machine built into Windows. Docker Desktop runs inside it.

**zram** — A swap device that lives in compressed RAM instead of on disk. Much faster than disk swap, at the cost of some CPU.
