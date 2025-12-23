"""Run validation with scope probes and print results to help inspect token scopes/metadata."""
import json

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from bibliometric_crawler import BibliometricCrawler


if __name__ == "__main__":
    bc = BibliometricCrawler()
    # Force a fresh validation run
    res = bc.validate_keys(invalidate_cache=True)
    print(json.dumps(res, indent=2))
    # Print any scope info available
    for name, info in res.items():
        sc = info.get("scopes") or info.get("scopes")
        if sc:
            print(f"{name}: scopes/metadata: {sc}")
