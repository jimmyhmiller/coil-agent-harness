# Snake factory benchmark — 2026-08-15

All runs produced a native GUI Coil Snake game with four-direction wrapping and ten
passing behavioral tests. Times are summed harness worker durations. Token values are
provider-reported cumulative usage.

| Metric | Original Luna Max | Optimized Luna Max | Optimized Terra Medium |
|---|---:|---:|---:|
| Worker attempts | 9 | 3 | 5 |
| Completed model turns | 87 | 70 | 73 |
| Tool calls | 109 | 95 | 79 |
| Worker duration | 1,199.9 s | 698.3 s | 665.6 s |
| Input tokens | 1,538,919 | 1,828,513 | 885,058 |
| Cached input tokens | 522,752 | 778,752 | 691,712 |
| Uncached input tokens | 1,016,167 | 1,049,761 | 193,346 |
| Output tokens | 54,573 | 30,114 | 12,899 |
| Reasoning tokens | 26,796 | 16,997 | 2,711 |
| Request-body high-water mark | not recorded | 233,725 bytes | 102,410 bytes |
| Product source + test lines | ~340 | 530 | 327 |

## Results

Compared with the original Luna Max run, optimized Terra Medium reduced:

- worker duration by 44.5%;
- total input tokens by 42.5%;
- uncached input tokens by 81.0%;
- output tokens by 76.4%;
- reasoning tokens by 89.9%;
- tool calls by 27.5%.

Compared with optimized Luna Max, Terra Medium used 51.6% fewer input tokens and 57.2%
fewer output tokens, with similar worker duration. Terra took three more completed
turns, but each turn carried much less context.

The workflow changes alone were not sufficient: optimized Luna Max was 41.8% faster
than the original run and used fewer turns, but consumed 18.8% more cumulative input
tokens. Luna's GUI worker expanded to 42 completed turns and a 233 KB request body.

Terra Medium needed automatic corrective retries. Its first engine passed static gates
but hung in the movement test; the supervisor captured the process tree and the next
attempt isolated and repaired the infinite loop. Its first GUI attempt made no useful
workspace change; the missing `WindowShouldClose` gate triggered a second attempt.

## Evidence

- Original journals: `.factory-runs/coil-snake/1786761905-13fe2997`,
  `.factory-runs/coil-snake/1786762388-6aecc071`, and
  `.factory-runs/coil-snake/1786762544-ff6a660b`.
- Optimized Luna Max journal and metrics:
  `.factory-runs/coil-snake/1786765288-10a5bb6b/`.
- Optimized Terra Medium journal and metrics:
  `.factory-runs/coil-snake/1786766050-d12d1990/`.
- Terra product workspace: `.factory-workspaces/coil-snake-6_y4icdm/`.
