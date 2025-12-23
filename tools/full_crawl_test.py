#!/usr/bin/env python3
"""
full_crawl_test.py

Lightweight script to run a single test query against all crawler implementations
in this project and print a concise summary of results.

Usage:
    python full_crawl_test.py [--query "machine learning"] [--max-results 5]
                              [--sample 3] [--databases wos,scopus] [--out results.json]
                              [--skip-missing-keys] [--concurrency 4] [--verbose]

Notes:
- The script intentionally runs crawlers sequentially (default) to be polite to APIs.
- Some crawlers require API keys or institutional access; if keys are missing, the
  crawler may return an empty result or print a note that credentials are required.
- This script does not expose or print any environment secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# Load .env if present (optional)
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    load_dotenv = None  # type: ignore

# Import crawler classes
try:
    from crawlers import (
        EBSCOCrawler,
        ERICCrawler,
        GeneCrawler,
        GenomeCrawler,
        IEEECrawler,
        PubChemCrawler,
        PubMedCrawler,
        SAGECrawler,
        ScienceDirectCrawler,
        ScopusCrawler,
        SpringerCrawler,
        WileyCrawler,
        WoSCrawler,
    )
except Exception as e:
    print("ERROR: failed to import crawlers module. Are dependencies installed?")
    print("Import error:", e)
    sys.exit(2)


# Mapping of crawler short names to (class, env var storing API key)
CRAWLERS = {
    "wos": (WoSCrawler, "WOS_API_KEY"),
    "scopus": (ScopusCrawler, "SCOPUS_API_KEY"),
    "sciencedirect": (ScienceDirectCrawler, "SCIENCEDIRECT_API_KEY"),
    "pubmed": (PubMedCrawler, "PUBMED_API_KEY"),
    "pubchem": (PubChemCrawler, "PUBCHEM_API_KEY"),
    "gene": (GeneCrawler, "GENE_API_KEY"),
    "genome": (GenomeCrawler, "GENOME_API_KEY"),
    "sage": (SAGECrawler, "SAGE_API_KEY"),
    "ieee": (IEEECrawler, "IEEE_API_KEY"),
    "eric": (ERICCrawler, "ERIC_API_KEY"),
    "springer": (SpringerCrawler, "SPRINGER_API_KEY"),
    "ebsco": (EBSCOCrawler, "EBSCO_API_KEY"),
    "wiley": (WileyCrawler, "WILEY_API_KEY"),
}


def instantiate_crawler(name: str, cls: Any) -> Tuple[Any, Optional[str]]:
    """
    Instantiate a crawler using the corresponding environment variable (if any).
    Returns (instance, used_api_key_env_var_value_or_None).
    """
    api_var = CRAWLERS[name][1]
    api_val = os.getenv(api_var) if api_var else None
    try:
        instance = cls(api_val) if api_var is not None else cls()
    except TypeError:
        # Some crawlers accept no args
        instance = cls()
    except Exception as e:
        raise RuntimeError(f"Failed to instantiate {name} crawler: {e}")
    return instance, api_val


def run_crawler(
    name: str,
    cls: Any,
    query: str,
    max_results: int,
    sample_count: int,
    skip_missing_keys: bool,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Run a single crawler and collect results and diagnostics.
    Returns a dict summary.
    """
    api_var = CRAWLERS[name][1]
    api_val = os.getenv(api_var) if api_var else None

    summary: Dict[str, Any] = {
        "name": name,
        "status": "unknown",
        "count": 0,
        "samples": [],
        "error": None,
        "time_s": 0.0,
        "used_api_key": bool(api_val),
    }

    if skip_missing_keys and api_var and not api_val:
        summary["status"] = "skipped_missing_key"
        summary["error"] = f"Missing {api_var}"
        return summary

    try:
        crawler, _ = instantiate_crawler(name, cls)
    except Exception as ex:
        summary["status"] = "error_instantiate"
        summary["error"] = str(ex)
        return summary

    start = time.time()
    try:
        # Call the crawler search method
        results = crawler.search(query, max_results=max_results)
        end = time.time()
        summary["time_s"] = round(end - start, 2)

        if not isinstance(results, list):
            # Some crawlers might return empty dicts or other shapes in failure case
            summary["status"] = "unexpected_response_type"
            summary["error"] = f"Expected list, got {type(results)}"
            return summary

        summary["count"] = len(results)
        summary["status"] = "ok" if len(results) > 0 else "no_results"

        # Build sample entries (title + url if available)
        samples = []
        for item in results[:sample_count]:
            title = item.get("title") or item.get("doi") or "<no title>"
            url = item.get("url", "")
            samples.append({"title": title, "url": url})
        summary["samples"] = samples

        if verbose:
            print(f"[{name}] OK - {len(results)} results in {summary['time_s']}s")
    except Exception as e:
        end = time.time()
        summary["time_s"] = round(end - start, 2)
        summary["status"] = "error"
        summary["error"] = str(e)
        if verbose:
            print(f"[{name}] ERROR after {summary['time_s']}s: {e}")

    return summary


def print_summary(results: List[Dict[str, Any]]) -> None:
    """Print a compact summary table and per-crawler details."""
    print("\n" + "=" * 80)
    print("Full crawl test summary")
    print("=" * 80)

    total_ok = sum(1 for r in results if r["status"] == "ok")
    total_no = sum(1 for r in results if r["status"] == "no_results")
    total_err = sum(1 for r in results if r["status"] == "error")
    total_skipped = sum(1 for r in results if r["status"].startswith("skipped"))
    print(f"Databases tested: {len(results)}")
    print(f" - OK (>=1 result): {total_ok}")
    print(f" - No results: {total_no}")
    print(f" - Errors: {total_err}")
    print(f" - Skipped: {total_skipped}\n")

    for r in results:
        name = r["name"]
        status = r["status"]
        count = r["count"]
        t = r["time_s"]
        print(f"[{name}] status={status} count={count} time={t}s")
        if r["error"]:
            print(f"   error: {r['error']}")
        if r.get("used_api_key"):
            print("   note: API key was present for this crawler")
        if r["samples"]:
            for s in r["samples"]:
                # truncate long titles
                title = s["title"]
                if len(title) > 140:
                    title = title[:137] + "..."
                url = s.get("url", "")
                print(f"   - {title} | {url}")
        print("")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a full crawl test over all crawlers."
    )
    parser.add_argument(
        "--query", "-q", default="machine learning", help="Query to run"
    )
    parser.add_argument(
        "--max-results",
        "-m",
        type=int,
        default=5,
        help="Max results to request per crawler (small value recommended)",
    )
    parser.add_argument(
        "--sample",
        "-s",
        type=int,
        default=3,
        help="How many sample titles to show per crawler",
    )
    parser.add_argument(
        "--databases",
        "-d",
        type=str,
        default="",
        help="Comma-separated short names of databases to test (default = all)",
    )
    parser.add_argument(
        "--out",
        "-o",
        type=str,
        default="",
        help="Optional path to write full JSON results (e.g., results.json)",
    )
    parser.add_argument(
        "--skip-missing-keys",
        action="store_true",
        help="Skip crawlers that require an API key when the env var is missing",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print more verbose debug information"
    )

    args = parser.parse_args(argv)

    query = args.query
    max_results = max(1, args.max_results)
    sample_count = max(0, args.sample)
    skip_missing = args.skip_missing_keys
    verbose = args.verbose

    # Build list of crawler names to run
    selected = []
    if args.databases:
        for token in args.databases.split(","):
            t = token.strip().lower()
            if t:
                if t in CRAWLERS:
                    selected.append(t)
                else:
                    print(f"Warning: unknown crawler '{t}' - skipping")
    else:
        selected = list(CRAWLERS.keys())

    results = []
    print(f"Running full crawl test for query: {query!r}")
    print(f"Testing: {', '.join(selected)}")
    print(f"Max results per crawler: {max_results}")
    print("Starting...")

    for name in selected:
        cls, _ = CRAWLERS[name]
        try:
            r = run_crawler(
                name=name,
                cls=cls,
                query=query,
                max_results=max_results,
                sample_count=sample_count,
                skip_missing_keys=skip_missing,
                verbose=verbose,
            )
        except Exception as exc:
            r = {
                "name": name,
                "status": "error",
                "count": 0,
                "samples": [],
                "error": str(exc),
                "time_s": 0.0,
                "used_api_key": bool(
                    os.getenv(CRAWLERS[name][1]) if CRAWLERS[name][1] else False
                ),
            }
        results.append(r)

    print_summary(results)

    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(results, fh, indent=2, ensure_ascii=False)
            print(f"Results written to: {args.out}")
        except Exception as exc:
            print(f"Failed to write results to {args.out}: {exc}")

    # Return non-zero exit if all crawlers failed or were skipped
    any_ok = any(r["status"] == "ok" for r in results)
    if not any_ok:
        print(
            "No crawler returned any results. Please check API keys and network access."
        )
        return 2

    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(130)
