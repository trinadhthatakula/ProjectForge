# Performance benchmarks

`benchmark_projectforge.py` measures local helper operations over synthetic manifests and capability inventories. It includes manifest validation, Markdown rendering, offline HTML rendering, team optimization, and capability matching. Feature count and discovered-skill count scale together so the larger cases exercise both project and inventory growth.

Run the default benchmark from the repository root:

```sh
python3 benchmarks/benchmark_projectforge.py > /tmp/projectforge-benchmark.json
```

Use `--sizes 10,100,1000` and `--iterations 9` to reproduce the checked-in baseline's workload, or choose other unique positive sizes. Each operation gets one warmup call by default. Results report median and nearest-rank p95 in milliseconds using `time.perf_counter_ns`.

The baseline in [`baseline-1.0.0.json`](baseline-1.0.0.json) records the ProjectForge 1.0.0 code revision on one Apple arm64 macOS host with CPython 3.12.9. It is an observation from that environment, not a performance guarantee. Compare runs on the same hardware, Python version, and revision; ordinary host load and filesystem state can affect timings. No pass/fail thresholds are imposed, and the benchmark makes no network calls.

Baseline median time in milliseconds:

| Features and skills | Validate | Markdown | Offline HTML | Optimize team | Match capabilities |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 122.307 | 0.548 | 0.836 | 29.642 | 52.828 |
| 100 | 87.704 | 2.012 | 5.782 | 183.057 | 277.594 |
| 1,000 | 108.391 | 19.158 | 44.313 | 1,610.283 | 1,151.472 |

The JSON file also includes nearest-rank p95 samples and environment metadata.

These are microbenchmarks of local helper functions, not provider response times, end-to-end CLI latency, or maximum supported project sizes. Each benchmark checks that its synthetic manifest validates before timing. Capability matching also mutates the in-memory manifest's capability report as part of its normal behavior.
