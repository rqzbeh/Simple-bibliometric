#!/usr/bin/env python3
"""
Integration test script for Simple-bibliometric.

This script exercises a few crawlers that can work without API keys (or with
optional package-based clients):
  - PubChem (using pubchempy if available, otherwise PUG REST)
  - SAGE (CrossRef: using habanero if available, otherwise REST)
  - PubMed (NCBI E-utilities via REST)

Usage:
  python integration_test.py [--pubchem QUERY] [--sage QUERY] [--pubmed QUERY]
                            [--max-results N]

Notes:
- This is intended as a lightweight integration check; it prints concise
  summaries of results and does not expose any API keys.
- The script respects the already-existing crawler implementations and
  the project .env/.env.example for configuration (dotenv).
"""

from __future__ import annotations

import argparse
import sys
import traceback

from dotenv import load_dotenv

# Load environment variables (if .env exists)
load_dotenv()

from crawlers import (
    BIOPYTHON_AVAILABLE,
    CROSSREF_AVAILABLE,
    PUBCHEMPY_AVAILABLE,
    PubChemCrawler,
    PubMedCrawler,
    SAGECrawler,
)


def _print_header(title: str):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def _summarize_pubchem_results(results: list, limit: int = 3):
    if not results:
        print("  (no PubChem results)")
        return
    for r in results[:limit]:
        title = r.get("title", "<no title>")
        cid = r.get("cid", "")
        url = r.get("url", "")
        print(f"  - {title} (CID: {cid}) {url}")


def _summarize_crossref_results(results: list, limit: int = 3):
    if not results:
        print("  (no CrossRef / SAGE results)")
        return
    for r in results[:limit]:
        title = r.get("title", "<no title>")
        doi = r.get("doi", "")
        journal = r.get("journal", "")
        url = r.get("url", "")
        print(f"  - {title} | DOI: {doi} | Journal: {journal} | {url}")


def _summarize_pubmed_results(results: list, limit: int = 3):
    if not results:
        print("  (no PubMed results)")
        return
    for r in results[:limit]:
        title = r.get("title", "<no title>")
        pmid = r.get("pmid", "")
        url = r.get("url", "")
        print(f"  - PMID {pmid} | {title} | {url}")


def run_pubchem_test(query: str, max_results: int = 5) -> bool:
    print(f"[PubChem] Query: {query}")
    print(f"  - pubchempy available: {PUBCHEMPY_AVAILABLE}")
    crawler = PubChemCrawler()  # Will prefer pubchempy if installed
    try:
        results = crawler.search(query, max_results)
        print(f"  - Results found: {len(results)}")
        _summarize_pubchem_results(results, limit=3)
        return len(results) > 0
    except Exception as e:
        print(f"  - PubChem search error: {e}")
        traceback.print_exc()
        return False


def run_sage_test(query: str, max_results: int = 5) -> bool:
    print(f"[SAGE / CrossRef] Query: {query}")
    print(f"  - habanero Crossref available: {CROSSREF_AVAILABLE}")
    crawler = SAGECrawler()  # Will prefer habanero if installed
    try:
        results = crawler.search(query, max_results)
        print(f"  - Results found: {len(results)}")
        _summarize_crossref_results(results, limit=3)
        return len(results) > 0
    except Exception as e:
        print(f"  - SAGE/CrossRef search error: {e}")
        traceback.print_exc()
        return False


def run_pubmed_test(query: str, max_results: int = 5) -> bool:
    print(f"[PubMed] Query: {query}")
    print(f"  - Biopython (Entrez) available: {BIOPYTHON_AVAILABLE}")
    crawler = PubMedCrawler()
    try:
        results = crawler.search(query, max_results)
        print(f"  - Results found: {len(results)}")
        _summarize_pubmed_results(results, limit=3)
        return len(results) > 0
    except Exception as e:
        print(f"  - PubMed search error: {e}")
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Run simple integration checks for crawlers"
    )
    parser.add_argument(
        "--pubchem", default="aspirin", help="PubChem query (default: aspirin)"
    )
    parser.add_argument(
        "--sage",
        default="machine learning",
        help="SAGE/CrossRef query (default: machine learning)",
    )
    parser.add_argument(
        "--pubmed", default="cancer", help="PubMed query (default: cancer)"
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=5,
        help="Max results to fetch per source (default: 5)",
    )
    args = parser.parse_args()

    _print_header("Simple-bibliometric Integration Tests")
    print(
        "Note: This script performs live network requests. It prints concise summaries only.\n"
    )

    # Run tests
    pubchem_ok = run_pubchem_test(args.pubchem, args.max_results)
    sage_ok = run_sage_test(args.sage, args.max_results)
    pubmed_ok = run_pubmed_test(args.pubmed, args.max_results)

    print("\n" + "=" * 60)
    print("Summary:")
    print(f"  PubChem: {'OK' if pubchem_ok else 'NO RESULTS / ERROR'}")
    print(f"  SAGE/CrossRef: {'OK' if sage_ok else 'NO RESULTS / ERROR'}")
    print(f"  PubMed: {'OK' if pubmed_ok else 'NO RESULTS / ERROR'}")
    print("=" * 60)

    # Exit code: 0 if all tests returned at least one result; 2 otherwise
    success = pubchem_ok and sage_ok and pubmed_ok
    sys.exit(0 if success else 2)


if __name__ == "__main__":
    main()
