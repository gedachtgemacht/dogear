---
name: performance
description: Measure first, then optimize: profiling, algorithmic complexity, caching, batching, honest benchmarks
triggers: performance, too slow, is slow, very slow, slower, faster, speed up, optimize, optimise, optimization, optimisation, profile, profiling, benchmark, latency, bottleneck, memory usage, memory leak, langsam, schneller, optimieren, optimierung, flaschenhals
---
# Performance

1. **Define the target.** Write down the metric and a number: "report generation takes 12 s, goal under 2 s". No target, no optimization.
2. **Measure before changing.** Reproduce with a fixed input of realistic size. Record the baseline. Do not guess where the time goes; a guess is wrong more often than right.
3. **Profile to find the hot path.** Python: `python -m cProfile -s cumtime script.py` (or `py-spy`), memory with `tracemalloc`. Node: `--cpu-prof`. Shell and services: `time`, request timings, `EXPLAIN` for queries. Look at the top 3 entries by cumulative time; ignore the rest.
4. **Fix algorithmic cost first.** Nested loops over the same data (O(n^2)), repeated list lookups (`x in list` instead of a set or dict), re-sorting in a loop, string concatenation in a loop, querying inside a loop (N+1). Going from O(n^2) to O(n log n) beats any micro-optimization by orders of magnitude.
5. **Then I/O.** Batch many small reads, writes or requests into few big ones. Stream large files instead of loading them whole. Run independent network calls concurrently. Add indexes for slow queries.
6. **Then cache**, only pure or slowly changing results: key them fully, bound the size (LRU), and define how they are invalidated. A cache with no expiry is a bug.
7. **Memory.** Generators instead of lists for big sequences, process data in chunks, release references, check the peak not the average.
8. **Micro-optimizations last**, and only inside a measured hot path that is still too slow. Never trade clarity for a gain under 10 percent.

**Benchmark honestly:**
- Warm up first (2 to 3 runs thrown away: caches, JIT, imports).
- Repeat at least 5 times, preferably 10 to 30 for fast operations.
- Report median and spread (min and max, or standard deviation), not one number.
- Same machine, same input, same load; change one thing at a time.
- Compare against the baseline in the same session and show both.

Avoid: optimizing code that runs once, caching without measuring, removing correctness checks for speed, "it feels faster", benchmarking with tiny inputs.

Verify: run the tests (behavior unchanged), re-run the benchmark, and report before and after with variance.
