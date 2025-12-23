"""Simple performance benchmark for crawl_databases.

This script injects synthetic crawlers with controlled latencies to compare
sequential vs concurrent crawling performance (change `max_workers` on
`BibliometricCrawler` to compare).

Usage:
    python tools/perf_benchmark.py
"""
import time

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from bibliometric_crawler import BibliometricCrawler


class SlowCrawler:
    def __init__(self, delay=0.5, name="slow"):
        self.delay = delay
        self.name = name

    def search(self, query, max_results=10):
        time.sleep(self.delay)
        return [{"title": f"{self.name}:{query}"}]


def run_benchmark(max_workers, n_dbs=6, per_call_delay=0.5, terms=3):
    bc = BibliometricCrawler(max_workers=max_workers)
    # Replace crawlers with slow fake ones
    names = list(bc.crawlers.keys())[:n_dbs]
    for i, n in enumerate(names):
        bc.crawlers[n] = SlowCrawler(delay=per_call_delay, name=n)

    analysis = {"search_terms": [f"t{i}" for i in range(terms)], "databases": names}
    start = time.time()
    results = bc.crawl_databases(analysis, max_results=1)
    elapsed = time.time() - start

    total_calls = len(names) * terms
    print(f"max_workers={max_workers}: elapsed={elapsed:.2f}s total_calls={total_calls}")
    return elapsed


if __name__ == "__main__":
    print("Running benchmarks (sequential vs concurrent)...\n")
    seq = run_benchmark(max_workers=1, n_dbs=6, per_call_delay=0.5, terms=3)
    par = run_benchmark(max_workers=8, n_dbs=6, per_call_delay=0.5, terms=3)
    print("\nSummary:")
    print(f"  sequential: {seq:.2f}s")
    print(f"  parallel  : {par:.2f}s")
    if par < seq:
        print("Parallelism provided a speedup: {:.2f}x".format(seq / par))
    else:
        print("No parallel speedup observed; investigate thread contention or GIL-bound workloads.")