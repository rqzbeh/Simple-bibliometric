import json
import traceback
import os
import sys

# Ensure project root is importable when running from scripts/
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bibliometric_crawler import BibliometricCrawler


bc = BibliometricCrawler()
print("MISSING KEYS:", bc.get_missing_api_keys())
print("EFFECTIVE KEYS:", json.dumps(bc.get_effective_api_keys(), indent=2))

# Print redacted headers/diagnostics for providers when possible
print("\nProvider diagnostics")
for name, crawler in bc.crawlers.items():
    try:
        hdrs = crawler._get_headers()
    except Exception:
        hdrs = {}
    # redact sensitive headers
    redacted = {}
    for k, v in (hdrs or {}).items():
        if any(x in k.lower() for x in ["api", "key", "token"]):
            redacted[k] = "<redacted>"
        else:
            redacted[k] = v
    print(f"- {name}: headers={json.dumps(redacted)}")


try:
    res = bc.process_query("cancer genomics", max_results=5)
    print("\nPROCESS COMPLETE\nResult summary:", json.dumps(res.get("result_summary", {}), indent=2))
    print("\nProviders: analysis:", res.get("analysis_provider"), "filtering:", res.get("filtering_provider"))
except Exception as e:
    print("ERROR DURING PROCESS_QUERY:", e)
    traceback.print_exc()
