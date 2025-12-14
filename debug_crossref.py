#!/usr/bin/env python3
"""
debug_crossref.py

A small, self-contained debug script to query CrossRef and inspect/filter
results for SAGE publications (publisher or container-title containing "sage").

Usage examples:
  # Basic usage (default query: "machine learning")
  python debug_crossref.py

  # Custom query, request more rows and print 10 samples
  python debug_crossref.py --query "machine learning" --rows 200 --sample 10

  # Save SAGE-filtered items to a JSON file
  python debug_crossref.py --query "healthcare" --rows 500 --outfile sage_items.json

Notes:
- CrossRef does not require an API key for basic queries.
- CrossRef respects polite agents: set CROSSREF_MAILTO or EMAIL environment
  variable to your contact email to include in the User-Agent header:
    export CROSSREF_MAILTO=you@example.com
- This script prints concise diagnostic messages and avoids printing secrets.
- If you plan to request many rows, please respect CrossRef rate limits.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from typing import Dict, List, Optional

import requests

CROSSREF_BASE = "https://api.crossref.org/works"
DEFAULT_ROWS = 100
MAX_ROWS_SAFE = 1000  # Practical upper limit for a single /works request


def build_user_agent() -> str:
    """
    Build a polite User-Agent string including a contact email if provided.
    CrossRef recommends including a contact email in the User-Agent.
    """
    contact = (
        os.getenv("CROSSREF_MAILTO") or os.getenv("NCBI_EMAIL") or os.getenv("EMAIL")
    )
    ua = "Simple-bibliometric-debug/1.0"
    if contact:
        return f"{ua} (mailto:{contact})"
    return f"{ua} (no-contact)"


def make_request(
    url: str, params: Dict[str, str], max_retries: int = 3
) -> Optional[Dict]:
    """
    Perform an HTTP GET with sensible retry and backoff behavior.
    Returns parsed JSON on success, or a dict describing the error.
    """
    headers = {"User-Agent": build_user_agent(), "Accept": "application/json"}
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (429, 503):  # rate limit / temporarily unavailable
                wait = (2 ** (attempt - 1)) * 1.0
                print(
                    f"[WARN] HTTP {resp.status_code} - sleeping {wait}s and retrying...",
                    file=sys.stderr,
                )
                time.sleep(wait)
                continue
            # For other status codes, return the error payload for debugging
            print(
                f"[ERROR] HTTP {resp.status_code}: {resp.text[:1000]}", file=sys.stderr
            )
            return {"_error": True, "status_code": resp.status_code, "text": resp.text}
        except requests.RequestException as exc:
            wait = (2 ** (attempt - 1)) * 1.0
            print(
                f"[ERROR] Request exception: {exc}. Retrying in {wait}s...",
                file=sys.stderr,
            )
            time.sleep(wait)
    return None


def query_crossref(
    query: str, rows: int = DEFAULT_ROWS, select: Optional[List[str]] = None
) -> List[Dict]:
    """
    Query CrossRef /works endpoint and return the list of items (raw).
    - 'select' is optional; leave it empty by default to avoid potential validation errors.
    """
    if rows > MAX_ROWS_SAFE:
        print(
            f"[WARN] rows={rows} is large; consider reducing to <= {MAX_ROWS_SAFE} to be polite.",
            file=sys.stderr,
        )

    params: Dict[str, str] = {"query": query, "rows": str(rows)}
    if select:
        # The 'select' parameter can be useful but can also cause validation errors if unsupported fields are included.
        params["select"] = ",".join(select)

    data = make_request(CROSSREF_BASE, params)
    if not data:
        raise RuntimeError(
            "No response from CrossRef API (request failed or timed out)."
        )
    if isinstance(data, dict) and data.get("_error"):
        raise RuntimeError(
            f"CrossRef returned HTTP {data.get('status_code')}: {data.get('text')[:400]}"
        )
    if not isinstance(data, dict) or "message" not in data:
        raise RuntimeError("Unexpected response structure from CrossRef API.")
    return data["message"].get("items", [])


def is_sage_item(item: Dict) -> bool:
    """
    Heuristic to detect if an item is from SAGE:
    - publisher field contains 'sage' (case-insensitive), OR
    - any container-title contains 'sage' (case-insensitive)
    """
    publisher = (item.get("publisher") or "").lower()
    if "sage" in publisher:
        return True
    container_titles = [ct.lower() for ct in (item.get("container-title") or []) if ct]
    for ct in container_titles:
        if "sage" in ct:
            return True
    return False


def filter_sage(items: List[Dict]) -> List[Dict]:
    """Return only items that match the SAGE heuristic."""
    return [it for it in items if is_sage_item(it)]


def summarize(items: List[Dict], sage_items: List[Dict], sample: int = 3) -> None:
    """Print a short summary of results and a few SAGE examples."""
    total = len(items)
    total_sage = len(sage_items)
    print(f"\nSummary:")
    print(f"  - Total CrossRef items returned: {total}")
    print(f"  - Items matching SAGE heuristics: {total_sage}")

    # Publisher distribution for diagnostics
    publishers = [(it.get("publisher") or "(unknown)").strip() for it in items]
    counter = Counter(publishers)
    print("\nTop publishers (by count):")
    for pub, cnt in counter.most_common(10):
        print(f"  - {pub}: {cnt}")

    if total_sage:
        print(f"\nSample SAGE items (up to {sample}):")
        for it in sage_items[:sample]:
            title = (it.get("title") or [""])[0] if it.get("title") else ""
            doi = it.get("DOI", "")
            publisher = it.get("publisher", "")
            container = (
                (it.get("container-title") or [""])[0]
                if it.get("container-title")
                else ""
            )
            url = f"https://doi.org/{doi}" if doi else it.get("URL", "")
            issued = it.get("issued") or it.get("published-print") or {}
            year = ""
            if issued and "date-parts" in issued and issued["date-parts"]:
                year = str(issued["date-parts"][0][0])
            print(f"  - {title} | {publisher} | {container} | {year} | {url}")


def main():
    parser = argparse.ArgumentParser(
        description="Debug CrossRef queries and inspect SAGE items"
    )
    parser.add_argument(
        "--query",
        "-q",
        default="machine learning",
        help="Search query (CrossRef 'query' param)",
    )
    parser.add_argument(
        "--rows",
        "-r",
        type=int,
        default=DEFAULT_ROWS,
        help=f"Number of rows to request (default: {DEFAULT_ROWS})",
    )
    parser.add_argument(
        "--sample",
        "-s",
        type=int,
        default=3,
        help="Number of example SAGE items to print",
    )
    parser.add_argument(
        "--select",
        "-S",
        nargs="+",
        help="Optional list of fields to include in 'select' (use with caution)",
    )
    parser.add_argument(
        "--outfile", "-o", help="Write SAGE-filtered results to JSON file"
    )
    parser.add_argument(
        "--show-raw",
        action="store_true",
        help="Print a single raw item (truncated) for debugging",
    )
    args = parser.parse_args()

    print("CrossRef debug tool")
    print(f"  User-Agent: {build_user_agent()}")
    print(f"  Query: {args.query!r}, rows: {args.rows}, sample: {args.sample}")
    if args.select:
        print(f"  Select fields: {args.select}")

    try:
        items = query_crossref(args.query, rows=args.rows, select=args.select)
    except Exception as exc:
        print(f"[ERROR] Query failed: {exc}", file=sys.stderr)
        sys.exit(2)

    sage_items = filter_sage(items)
    summarize(items, sage_items, sample=args.sample)

    if args.show_raw and items:
        raw = json.dumps(items[0], indent=2)
        print("\nRaw sample item (truncated):")
        print(raw[:8000] + ("\n... (truncated)" if len(raw) > 8000 else ""))

    if args.outfile:
        try:
            with open(args.outfile, "w", encoding="utf-8") as fh:
                json.dump(sage_items, fh, indent=2, ensure_ascii=False)
            print(f"\nWrote {len(sage_items)} SAGE items to: {args.outfile}")
        except Exception as exc:
            print(f"[ERROR] Failed to write to {args.outfile}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
