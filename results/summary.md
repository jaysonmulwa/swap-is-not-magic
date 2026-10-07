## spike: 150 MB steady, +200 MB for 2 s

| config | OOM-killed | rps before | spike took (s) | rps 1s after | rps 5s after | rps 10s after | rps 20s after | back to 90% after (s) |
|---|---|---|---|---|---|---|---|---|
| no swap | 3/3 | 15294 | - | - | - | - | - | - |
| 512 MB swap | 0/3 | 17054 | 2.4 | 92 | 286 | 16169 | 15787 | 9 |

## cold: idle memory next to a hot set

| config | OOM-killed | rps | p50 (us) | p99 (us) | max (us) | major faults | CPU % |
|---|---|---|---|---|---|---|---|
| hot 100 MB only, no swap | 0/3 | 15599 | 56.0 | 156.1 | 10282.2 | 0 | 101 |
| + cold 200 MB, no swap | 3/3 | - | - | - | - | - | - |
| + cold 200 MB, 512 MB swap | 0/3 | 15613 | 58.3 | 149.1 | 10245.8 | 0 | 100 |

## workingset: everything hot, 256 MB RAM, 1 GB swap

| config | OOM-killed | rps | p50 (us) | p99 (us) | max (us) | major faults | CPU % |
|---|---|---|---|---|---|---|---|
| 64 MB | 0/3 | 16622 | 52.8 | 125.9 | 7910.4 | 0 | 100 |
| 128 MB | 0/3 | 13828 | 63.7 | 168.3 | 9054.3 | 0 | 101 |
| 192 MB | 0/3 | 14408 | 61.7 | 155.8 | 5195.5 | 0 | 100 |
| 224 MB | 0/3 | 13870 | 66.0 | 157.0 | 5036.8 | 0 | 101 |
| 256 MB | 0/3 | 4016 | 99.0 | 1299.5 | 20871.6 | 18625 | 52 |
| 288 MB | 0/3 | 396 | 2022.4 | 10428.8 | 28952.2 | 31212 | 21 |
| 320 MB | 0/3 | 285 | 3155.6 | 10728.2 | 33500.5 | 38604 | 22 |
| 384 MB | 0/3 | 164 | 5671.8 | 13936.8 | 34318.1 | 35915 | 19 |
| 512 MB | 0/3 | 109 | 8504.1 | 18548.0 | 58381.6 | 35478 | 21 |

## moreswap: does more swap help a thrashing set?

| config | OOM-killed | rps | p50 (us) | p99 (us) | max (us) | major faults | CPU % |
|---|---|---|---|---|---|---|---|
| 384 MB hot, 512 MB swap | 0/3 | 173 | 5178.2 | 17369.5 | 25096.6 | 37991 | 19 |
| 384 MB hot, 2 GB swap | 0/3 | 153 | 5903.9 | 16318.1 | 30771.7 | 33573 | 21 |

## leak: 64 MB hot, leaking 16 MB/s

| config | OOM-killed | survived (s) | leaked at death (MB) | rps first 3s | rps last 3s | p99 last 3s (us) | alloc ms/s last 3s |
|---|---|---|---|---|---|---|---|
| 0 MB swap | 3/3 | 11.1 | 176 | 16101 | 17568 | 105.6 | 8 |
| 256 MB swap | 3/3 | 27.4 | 432 | 15211 | 16949 | 125.5 | 25 |
| 512 MB swap | 3/3 | 43.4 | 688 | 14704 | 16353 | 133.5 | 26 |
| 1024 MB swap | 3/3 | 75.7 | 1200 | 15962 | 17462 | 118.2 | 28 |
