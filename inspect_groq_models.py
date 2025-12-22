#!/usr/bin/env python3
"""
inspect_groq_models.py

Small utility to inspect available Groq models using the Groq Python client.

Features:
- List available Groq models
- Show model metadata
- Suggest a "best" model automatically via a small heuristic (prefers 'versatile' / larger suffix like '70b')
- Optionally perform a tiny test completion against a given model (explicit --test flag)
- Optionally write the chosen model into the local `.env` file (explicit --apply and --yes)

Usage examples:
  # List models
  python inspect_groq_models.py --list

  # Suggest best model
  python inspect_groq_models.py --suggest

  # Inspect a specific model
  python inspect_groq_models.py --inspect llama-3.1-70b-versatile

  # Suggest and test the suggested model
  python inspect_groq_models.py --suggest --test

  # Suggest and apply (write) to .env (requires --yes)
  python inspect_groq_models.py --suggest --apply --yes

Notes:
- Requires `groq` and `python-dotenv` to be installed and a valid GROQ_API_KEY present in env or .env.
- Be careful when using --test; it will make small API calls (low-cost but real calls).
- The program does not print or store secret API keys.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None  # type: ignore

# Import Groq client lazily to provide helpful message if missing
try:
    from groq import Groq  # type: ignore
except Exception:  # pragma: no cover - environment dependent
    Groq = None  # type: ignore


# ---------------------------
# Utility helpers
# ---------------------------
def ensure_dotenv_loaded() -> None:
    """Load .env if python-dotenv is available (silently no-op otherwise)."""
    if load_dotenv:
        load_dotenv()


def require_groq_client() -> Any:
    """Return a Groq client, or exit with a helpful message if unavailable."""
    ensure_dotenv_loaded()
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print(
            "ERROR: GROQ_API_KEY not found in environment variables or .env file.\n"
            "Please set GROQ_API_KEY before running this script (see README)."
        )
        sys.exit(2)

    if Groq is None:
        print(
            "ERROR: The `groq` Python package is not installed. Install it with:\n"
            "    pip install groq\n"
        )
        sys.exit(2)

    try:
        client = Groq(api_key=api_key)
    except Exception as exc:
        print(f"ERROR: Failed to initialize Groq client: {exc}")
        sys.exit(2)
    return client


def model_item_to_dict(item: Any) -> Dict[str, Any]:
    """
    Convert a model item (which may be a dict, pydantic model, or custom object)
    into a plain dict for inspection.
    """
    # dict-like
    if isinstance(item, dict):
        return dict(item)

    # pydantic v1: .dict(), pydantic v2: .model_dump()
    for attr in ("model_dump", "dict"):
        if hasattr(item, attr):
            try:
                fn = getattr(item, attr)
                res = fn() if callable(fn) else fn
                if isinstance(res, dict):
                    return dict(res)
            except Exception:
                pass

    # common attributes
    out: Dict[str, Any] = {}
    for k in getattr(item, "__dict__", {}).keys():
        try:
            out[k] = getattr(item, k)
        except Exception:
            out[k] = repr(getattr(item, k, None))
    # fallback: try attributes that are safe/simple
    for k in dir(item):
        if k.startswith("_"):
            continue
        if k in out:
            continue
        try:
            v = getattr(item, k)
        except Exception:
            continue
        if callable(v):
            continue
        try:
            json.dumps(v)  # quick check if JSON serializable
            out[k] = v
        except Exception:
            out[k] = repr(v)
    return out


def print_json(o: Any, indent: int = 2) -> None:
    print(json.dumps(o, indent=indent, ensure_ascii=False, default=str))


# ---------------------------
# Model listing & selection
# ---------------------------
@dataclass
class CandidateModel:
    id: str
    meta: Dict[str, Any]
    score: float = 0.0


def list_groq_models(client: Any) -> List[CandidateModel]:
    """
    Retrieve models via client.models.list() and convert to CandidateModel list.
    """
    try:
        models_resp = client.models.list()
    except Exception as exc:
        raise RuntimeError(f"Error listing Groq models: {exc}") from exc

    # models_resp might be a custom pydantic object; attempt to extract 'data' or iterate
    model_entries: Iterable[Any] = []
    if hasattr(models_resp, "data"):
        model_entries = getattr(models_resp, "data") or []
    elif isinstance(models_resp, dict) and "data" in models_resp:
        model_entries = models_resp.get("data", []) or []
    elif isinstance(models_resp, list):
        model_entries = models_resp
    else:
        # Try to inspect common attributes
        model_entries = getattr(models_resp, "models", []) or []

    candidates: List[CandidateModel] = []
    for raw in model_entries:
        m = model_item_to_dict(raw)
        model_id = m.get("id") or m.get("name") or m.get("model_id") or str(m)
        candidates.append(CandidateModel(id=str(model_id), meta=m))

    return candidates


def score_model(candidate: CandidateModel) -> float:
    """
    Heuristic scoring function to pick a 'best' model for general usage:
    - Boost if contains 'versatile' in id / name
    - Boost by numeric 'b' suffix (e.g., '70b' -> larger is better)
    - Boost if 'chat' or 'conversational' appears
    - Small bonus for presence of helpful metadata
    """
    m = candidate.meta
    model_id = (candidate.id or "").lower()
    name = str(m.get("name", "")).lower()
    score = 0.0

    # Prefer versatile models
    if "versatile" in model_id or "versatile" in name:
        score += 100.0

    # Chat hint
    if (
        "chat" in model_id
        or "chat" in name
        or "conversational" in str(m.get("description", "")).lower()
    ):
        score += 20.0

    # Extract numeric 'b' suffix like 70b, 13b, 7b
    m = re.search(r"(\d+)\s*[bB]", candidate.id)
    if m:
        try:
            bn = int(m.group(1))
            # weight by size; larger gets more score
            score += float(bn)
        except Exception:
            pass

    # Bonus if model advertises tokens or context
    for field in (
        "context_window",
        "max_context",
        "context_length",
        "max_input_tokens",
    ):
        if field in candidate.meta:
            try:
                score += float(candidate.meta.get(field, 0)) / 1000.0
            except Exception:
                pass

    # Small heuristic based on available descriptive text
    if len(str(candidate.meta.get("description", "")).strip()) > 40:
        score += 5.0

    return score


def pick_best_model(candidates: List[CandidateModel]) -> Optional[CandidateModel]:
    if not candidates:
        return None
    for c in candidates:
        c.score = score_model(c)
    # Sort by score desc, then by id for deterministic choice
    candidates.sort(key=lambda x: (-x.score, x.id))
    return candidates[0]


# ---------------------------
# Model testing
# ---------------------------
def test_model_chat(client: Any, model_id: str, timeout: int = 30) -> Dict[str, Any]:
    """
    Do a small, safe chat test against the model to validate it can be used:
    - Low max_tokens, low temperature
    - Returns dictionary with 'success' (bool) and 'response' or 'error' info
    """
    messages = [
        {"role": "system", "content": "You are a small test agent. Respond concisely."},
        {
            "role": "user",
            "content": "This is a quick model test. Reply with a single short token 'OK' followed by the model id.",
        },
    ]
    try:
        response = client.chat.completions.create(
            messages=messages,
            model=model_id,
            temperature=0.0,
            max_tokens=40,
        )
        # Attempt to extract a text content
        content = None
        try:
            content = response.choices[0].message.content
        except Exception:
            # Fall back to raw representation
            content = str(response)
        return {"success": True, "model": model_id, "response": content}
    except Exception as exc:  # pragma: no cover - runtime dependent
        return {"success": False, "model": model_id, "error": str(exc)}


# ---------------------------
# .env writing helper
# ---------------------------
def write_dotenv_variable(
    key: str, value: str, filename: str = ".env", backup: bool = True
):
    """
    Insert or replace a key=value pair in a .env file. Back up the original file if present.
    """
    if backup and os.path.exists(filename):
        import datetime
        import shutil

        ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        bak = f"{filename}.bak.{ts}"
        shutil.copyfile(filename, bak)
        print(f"Created backup of {filename} at {bak}")

    lines: List[str] = []
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    key_found = False
    for i, ln in enumerate(lines):
        if ln.strip().startswith(key + "="):
            lines[i] = f"{key}={value}"
            key_found = True
            break
    if not key_found:
        lines.append(f"{key}={value}")
    with open(filename, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"Wrote {key}={value} to {filename}")


# ---------------------------
# CLI & main
# ---------------------------
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect Groq models and suggest a default/fallback model."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--list", action="store_true", help="List available Groq models")
    group.add_argument(
        "--inspect", type=str, metavar="MODEL_ID", help="Inspect a specific model id"
    )
    group.add_argument(
        "--suggest", action="store_true", help="Suggest a best model via heuristics"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Perform a small completion test on the selected model",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Optionally write suggested model to .env (requires --yes)",
    )
    parser.add_argument(
        "--yes", action="store_true", help="Confirm changes when used with --apply"
    )
    parser.add_argument(
        "--limit", type=int, default=200, help="Limit number of models to display"
    )
    parser.add_argument("--json", type=str, help="Write model list to JSON file")
    args = parser.parse_args(argv)

    client = require_groq_client()

    try:
        candidates = list_groq_models(client)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 2

    if args.json:
        try:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump(
                    [c.meta for c in candidates],
                    fh,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            print(f"Wrote {len(candidates)} models to {args.json}")
        except Exception as exc:
            print(f"Failed to write JSON file: {exc}")

    if args.list:
        print(f"Found {len(candidates)} models (showing up to {args.limit}):\n")
        for idx, c in enumerate(candidates[: args.limit]):
            lowdesc = (str(c.meta.get("description", "") or "")[:120]).replace(
                "\n", " "
            )
            print(f"{idx + 1:3d}. {c.id}  | {lowdesc}")
        return 0

    if args.inspect:
        mid = args.inspect
        found = next((c for c in candidates if c.id == mid), None)
        if not found:
            print(f"Model id {mid!r} not found in the listed models.")
            print("Available models (first 20):")
            for c in candidates[:20]:
                print("  -", c.id)
            return 2
        print(f"Model: {found.id}")
        print_json(found.meta)
        return 0

    if args.suggest:
        best = pick_best_model(candidates)
        if not best:
            print("No models available to suggest.")
            return 2
        print("Suggested model based on heuristics:\n")
        print(f"  id: {best.id}")
        print(f"  score: {best.score:.2f}")
        print("  metadata (truncated):")
        # show relevant metadata fields if present
        interesting = {
            k: best.meta.get(k)
            for k in ("description", "family", "id", "name", "context_window")
            if k in best.meta
        }
        print_json(interesting)
        # Optionally test
        if args.test:
            print(
                "\nRunning a quick capability test for the suggested model (small chat completion)..."
            )
            res = test_model_chat(client, best.id)
            if res.get("success"):
                print("Test succeeded. Sample response (truncated):")
                out = res.get("response")
                if isinstance(out, str):
                    print(textwrap.shorten(out.replace("\n", " "), 300))
                else:
                    print_json(out)
            else:
                print("Test failed:")
                print(res.get("error"))
                # If the error indicates model decommission, attempt to pick next-best
                if res.get("error") and "decommission" in res.get("error", "").lower():
                    print(
                        "\nModel appears decommissioned; attempting to pick next-best fallback..."
                    )
                    # pick next candidate
                    if len(candidates) >= 2:
                        fallback = candidates.copy()
                        fallback = sorted(
                            fallback, key=lambda x: (-score_model(x), x.id)
                        )
                        # choose second item
                        if len(fallback) > 1:
                            alt = fallback[1]
                            print(f"Trying alternative model: {alt.id}")
                            alt_res = test_model_chat(client, alt.id)
                            if alt_res.get("success"):
                                print("Alternative model test succeeded.")
                                best = alt
                            else:
                                print(
                                    "Alternative model test failed:",
                                    alt_res.get("error"),
                                )
        # Apply to .env if requested
        if args.apply:
            if not args.yes:
                print(
                    "\nTo apply the suggested model to .env, re-run with --apply --yes"
                )
            else:
                try:
                    write_dotenv_variable("GROQ_MODEL", best.id)
                    print(
                        "Updated .env with GROQ_MODEL. (backup made if .env existed.)"
                    )
                except Exception as exc:
                    print(f"Failed to write .env: {exc}")
        else:
            print(
                f"\nTo set this as the default model, add to your environment:\n    export GROQ_MODEL={best.id}\nOr run with --apply --yes to update the local .env file."
            )
        return 0

    # Default behavior: no argument -> print summary + top 10 candidates
    print(f"Found {len(candidates)} models. Top candidates by heuristic score:\n")
    for idx, c in enumerate(
        sorted(candidates, key=lambda x: -score_model(x))[: min(20, len(candidates))]
    ):
        c.score = score_model(c)
        snippet = (str(c.meta.get("description", "") or "")[:120]).replace("\n", " ")
        print(f"{idx + 1:2d}. {c.id:40s} score={c.score:6.1f}  {snippet}")
    print(
        "\nUse --inspect MODEL_ID to see details, --suggest to pick one, --test to validate it."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(130)
