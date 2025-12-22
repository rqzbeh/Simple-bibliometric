"""
Disk-backed cache utilities for Simple-bibliometric.

This module provides:
- make_cache_key: create a stable key for arguments (tries JSON-friendly canonicalization)
- set_cache / get_cache: store/retrieve JSON-serializable or pickled values on disk with optional TTL
- clear_cache: remove cached files
- disk_cache: a decorator to cache function results to disk (with optional TTL)

Notes:
- The default cache directory is ".cache/" (can be overridden with env var BIB_CACHE_DIR).
- Values that are JSON-serializable are stored as human-readable JSON; other values fall back to pickle.
- When using pickle, be aware of untrusted data risks if you load cache files from untrusted sources.
- Atomic writes are used to avoid partially written cache files.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pickle
import tempfile
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path(os.getenv("BIB_CACHE_DIR", ".cache"))
DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# -------------------------
# Key creation / utilities
# -------------------------
def _canonicalize(obj: Any) -> Any:
    """
    Convert an object into a JSON-stable representation when possible.
    Fallbacks to repr() for non-serializable objects.
    """
    # Primitive types
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    # Bytes -> repr
    if isinstance(obj, (bytes, bytearray)):
        return repr(obj)
    # Iterable types
    if isinstance(obj, (list, tuple, set)):
        return [_canonicalize(x) for x in obj]
    if isinstance(obj, dict):
        # Sort keys to ensure deterministic ordering
        return {
            str(k): _canonicalize(obj[k])
            for k in sorted(obj.keys(), key=lambda x: str(x))
        }
    # Fallback: repr
    return repr(obj)


def make_cache_key(*args: Any, **kwargs: Any) -> str:
    """
    Create a stable cache key string from positional and keyword args.

    The key is JSON-encoded canonical representation and then hashed (SHA256) to produce
    a compact filename-friendly key.
    """
    payload = {"args": _canonicalize(args), "kwargs": _canonicalize(kwargs)}
    try:
        canon = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
    except Exception:
        # Fallback to repr if anything odd occurs
        canon = repr(payload)
    # Return the hex digest as the key string (shorten to 64 chars)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _json_path_for(key: str, cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    return cache_dir / f"{key}.json"


def _pkl_path_for(key: str, cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    return cache_dir / f"{key}.pkl"


# -------------------------
# Basic get/set/clear cache
# -------------------------
def set_cache(key: str, value: Any, cache_dir: Path = DEFAULT_CACHE_DIR) -> None:
    """
    Store `value` under `key`. Try JSON; if that fails, use pickle.
    Writes are atomic (write to temp file and replace).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    json_path = _json_path_for(key, cache_dir)
    pkl_path = _pkl_path_for(key, cache_dir)

    # Remove older variants
    for p in (json_path, pkl_path):
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass

    # Try JSON
    try:
        tmp = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8")
        with tmp as fh:
            json.dump(value, fh, ensure_ascii=False, indent=None)
        os.replace(tmp.name, str(json_path))
        logger.debug("Wrote JSON cache %s", json_path)
        return
    except Exception:
        # JSON serialization failed; fallback to pickle
        try:
            tmp = tempfile.NamedTemporaryFile("wb", delete=False)
            with tmp as fh:
                pickle.dump(value, fh, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp.name, str(pkl_path))
            logger.debug("Wrote PICKLE cache %s", pkl_path)
            return
        except Exception as e:
            logger.exception("Failed to write cache for key %s: %s", key, e)
            # Best-effort: don't raise; caching should be non-critical


def get_cache(
    key: str, ttl_seconds: Optional[int] = None, cache_dir: Path = DEFAULT_CACHE_DIR
) -> Optional[Any]:
    """
    Retrieve cached value for `key`. If TTL is provided, return None when stale.
    Checks JSON variant first, then pickle variant.
    """
    json_path = _json_path_for(key, cache_dir)
    pkl_path = _pkl_path_for(key, cache_dir)

    for path, loader in [(json_path, "json"), (pkl_path, "pkl")]:
        if not path.exists():
            continue
        if ttl_seconds is not None:
            try:
                mtime = path.stat().st_mtime
                if (time.time() - mtime) > float(ttl_seconds):
                    logger.debug("Cache file %s expired (ttl=%s)", path, ttl_seconds)
                    return None
            except Exception:
                # If we can't stat for some reason, continue to attempt load
                pass
        try:
            if loader == "json":
                with open(path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            else:
                with open(path, "rb") as fh:
                    return pickle.load(fh)
        except Exception:
            logger.exception("Failed to read cache file %s; ignoring", path)
            # Corrupt file -> ignore
            try:
                path.unlink()
            except Exception:
                pass
            return None
    return None


def clear_cache(cache_dir: Path = DEFAULT_CACHE_DIR) -> int:
    """
    Delete all cache files (JSON and PKL) in cache_dir.
    Returns the number of files removed.
    """
    removed = 0
    for entry in cache_dir.iterdir():
        if entry.is_file() and entry.suffix in (".json", ".pkl"):
            try:
                entry.unlink()
                removed += 1
            except Exception:
                logger.exception("Failed to remove cache file: %s", entry)
    return removed


# -------------------------
# Helper decorator
# -------------------------
def disk_cache(
    ttl_seconds: Optional[int] = None,
    key_fn: Optional[Callable[..., str]] = None,
    cache_dir: Optional[Path] = None,
):
    """
    Decorator to cache function results on disk.

    - ttl_seconds: time-to-live in seconds (None means no expiry)
    - key_fn: optional callable (func, args, kwargs) -> key string; if not provided, a key is derived from func name + args
    - cache_dir: optional Path to cache directory; defaults to DEFAULT_CACHE_DIR
    """

    def _decorator(func: Callable):
        local_cache_dir = cache_dir or DEFAULT_CACHE_DIR

        @wraps(func)
        def _wrapped(*args, **kwargs):
            try:
                if key_fn:
                    key = key_fn(func, args, kwargs)
                else:
                    # include function name to avoid collisions across different functions
                    raw_key = {"fn": func.__name__, "args": args, "kwargs": kwargs}
                    key = make_cache_key(raw_key)
            except Exception:
                # Fallback to a repr-based key if canonicalization fails
                key = hashlib.sha256(
                    repr((func.__name__, args, kwargs)).encode("utf-8")
                ).hexdigest()

            # Try to read from cache
            cached = get_cache(key, ttl_seconds=ttl_seconds, cache_dir=local_cache_dir)
            if cached is not None:
                logger.debug("disk_cache: hit for key=%s", key)
                return cached

            # Cache miss: call function
            logger.debug("disk_cache: miss for key=%s; calling %s", key, func.__name__)
            result = func(*args, **kwargs)
            try:
                set_cache(key, result, cache_dir=local_cache_dir)
            except Exception:
                # ignore cache write failures
                logger.exception("disk_cache: failed to set cache for key=%s", key)
            return result

        # Expose a helper to clear cache for this function (based on its name)
        def clear_this(ttl_seconds_local: Optional[int] = None):
            # Not precise (does not delete only keys for this func); we prefer not to implement selective deletion
            return clear_cache(local_cache_dir)

        _wrapped.clear_cache = clear_this  # type: ignore
        return _wrapped

    return _decorator


# -------------------------
# Module convenience exports
# -------------------------
__all__ = [
    "make_cache_key",
    "set_cache",
    "get_cache",
    "clear_cache",
    "disk_cache",
    "DEFAULT_CACHE_DIR",
]
