"""
Simple-bibliometric.jobs
------------------------

A small job queue abstraction that provides:

- An in-process (thread-pool) job backend suitable for development and small
  deployments. It exposes simple job submission, status inspection, result retrieval,
  cancellation and cleanup.
- Optional RQ (Redis Queue) backend support when the `rq` and `redis` packages are
  installed and you prefer off-process persistent job handling.

Usage (in-process):
    from jobs import default_manager, submit_job, get_job_info, get_job_result

    job_id = submit_job(my_long_running_function, arg1, kwarg=value)
    info = get_job_info(job_id)
    result = get_job_result(job_id, timeout=30)  # blocks up to timeout secs

Usage (RQ):
    # set environment REDIS_URL or pass redis_url to JobManager(..., backend='rq')
    mgr = JobManager(backend='rq')
    job_id = mgr.submit(my_task, ...)

Notes:
- The in-process backend stores results in RAM (not persistent across process restarts).
- The RQ backend requires `redis` and `rq` to be installed and Redis available.
"""

from __future__ import annotations

import datetime
import inspect
import logging
import os
import tempfile
import threading
import traceback
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("simple_bibliometric.jobs")
logger.addHandler(logging.NullHandler())

# Optional imports for RQ backend (import only when used)
try:
    import redis  # type: ignore
    import rq  # type: ignore

    _RQ_AVAILABLE = True
except Exception:
    _RQ_AVAILABLE = False


# Standardized job statuses
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_FINISHED = "finished"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"


def _now_iso() -> str:
    # Use timezone-aware UTC timestamp to avoid deprecation and ensure clarity
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


class JobNotFoundError(KeyError):
    pass


class BaseJobBackend:
    """Abstract base API for job backends."""

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
        raise NotImplementedError

    def status(self, job_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    def result(self, job_id: str, timeout: Optional[float] = None) -> Any:
        raise NotImplementedError

    def cancel(self, job_id: str) -> bool:
        raise NotImplementedError

    def list_jobs(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def shutdown(self, wait: bool = True):
        raise NotImplementedError

    def cleanup(self, older_than_seconds: int = 24 * 3600) -> int:
        """Remove finished jobs older than given seconds. Returns count removed."""
        raise NotImplementedError


class InProcessBackend(BaseJobBackend):
    """In-process job executor using ThreadPoolExecutor.

    Stores job metadata and results in memory. Suitable for development or small load.
    """

    def __init__(
        self,
        max_workers: int = 4,
        retention_seconds: int = 24 * 3600,
    ):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()
        # jobs: job_id -> dict with metadata and the future
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._retention_seconds = int(retention_seconds)

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
        job_id = uuid.uuid4().hex
        now = _now_iso()
        job_record = {
            "id": job_id,
            "status": STATUS_QUEUED,
            "created_at": now,
            "started_at": None,
            "finished_at": None,
            "result": None,
            "error": None,
            "traceback": None,
            "meta": {"fn": getattr(fn, "__name__", str(fn))},
            "future": None,  # will set below
        }

        def _run_callable(jid: str, callable_fn: Callable[..., Any], *a, **kw):
            start = _now_iso()
            with self._lock:
                job_record = self._jobs.get(jid)
                if job_record is None:
                    # Job may have been removed; nothing to do
                    return None
                job_record["status"] = STATUS_RUNNING
                job_record["started_at"] = start
            try:
                # Attempt to inject the job id into the callable when possible.
                # We prefer to pass as keyword `job_id` when the callable accepts it or
                # has a **kwargs parameter. If the callable's first positional
                # parameter is named `job_id`, we will pass it positionally.
                try:
                    sig = inspect.signature(callable_fn)
                    params = sig.parameters
                    accepts_var_kw = any(
                        p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
                    )
                    accepts_job_kw = "job_id" in params
                    first_param_accepts_jobid = False
                    if params:
                        first = next(iter(params.values()))
                        if (
                            first.kind
                            in (
                                inspect.Parameter.POSITIONAL_ONLY,
                                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                            )
                            and first.name == "job_id"
                        ):
                            first_param_accepts_jobid = True
                except Exception:
                    accepts_var_kw = False
                    accepts_job_kw = False
                    first_param_accepts_jobid = False

                if accepts_job_kw or accepts_var_kw:
                    res = callable_fn(*a, **kw, job_id=jid)
                elif first_param_accepts_jobid:
                    res = callable_fn(jid, *a, **kw)
                else:
                    res = callable_fn(*a, **kw)

                finish = _now_iso()
                with self._lock:
                    job_record["result"] = res
                    job_record["status"] = STATUS_FINISHED
                    job_record["finished_at"] = finish
                return res
            except Exception as exc:
                tb = traceback.format_exc()
                finish = _now_iso()
                with self._lock:
                    job_record["error"] = str(exc)
                    job_record["traceback"] = tb
                    job_record["status"] = STATUS_FAILED
                    job_record["finished_at"] = finish
                logger.exception("Job %s failed: %s", jid, exc)
                # Re-raise so future.result() gets the exception if awaited
                raise

        # Ensure the job record is visible in the shared job store *before* the runner
        # begins. This prevents a race where the runner starts and tries to look up
        # the job record but it has not yet been inserted.
        with self._lock:
            self._jobs[job_id] = job_record

        future: Future = self._executor.submit(
            _run_callable, job_id, fn, *args, **kwargs
        )

        # Attach the future to the already-published job record
        with self._lock:
            job_record["future"] = future
        return job_id

    def _get_job(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFoundError(job_id)
            return job

    def status(self, job_id: str) -> Dict[str, Any]:
        job = self._get_job(job_id)
        # Build a JSON-friendly snapshot (not including raw future)
        return {
            "id": job["id"],
            "status": job["status"],
            "created_at": job["created_at"],
            "started_at": job["started_at"],
            "finished_at": job["finished_at"],
            "error": job["error"],
            "has_result": job["result"] is not None,
            "meta": job.get("meta", {}),
        }

    def result(self, job_id: str, timeout: Optional[float] = None) -> Any:
        job = self._get_job(job_id)
        future: Future = job["future"]
        # This will raise the exception if the job failed
        return future.result(timeout=timeout)

    def cancel(self, job_id: str) -> bool:
        job = self._get_job(job_id)
        future: Future = job["future"]
        cancelled = future.cancel()
        with self._lock:
            if cancelled:
                job["status"] = STATUS_CANCELLED
                job["finished_at"] = _now_iso()
        return cancelled

    def list_jobs(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [self.status(jid) for jid in list(self._jobs.keys())]

    def shutdown(self, wait: bool = True):
        self._executor.shutdown(wait=wait)

    def cleanup(self, older_than_seconds: int = None) -> int:
        older_than_seconds = older_than_seconds or self._retention_seconds
        cutoff = datetime.datetime.utcnow().timestamp() - float(older_than_seconds)
        removed = 0
        with self._lock:
            to_remove = []
            for jid, rec in list(self._jobs.items()):
                finished = rec.get("finished_at")
                if finished:
                    try:
                        ts = datetime.datetime.fromisoformat(
                            finished.rstrip("Z")
                        ).timestamp()
                    except Exception:
                        ts = 0
                    if ts < cutoff:
                        to_remove.append(jid)
            for jid in to_remove:
                try:
                    del self._jobs[jid]
                    removed += 1
                except Exception:
                    pass
        return removed


class RQBackend(BaseJobBackend):
    """RQ-backed job backend (requires `rq` and `redis` packages).

    Note: jobs executed by RQ must be importable callables; RQ persists the jobs and results in Redis.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        queue_name: str = "simple-bib-queue",
    ):
        if not _RQ_AVAILABLE:
            raise RuntimeError(
                "RQ backend requires `rq` and `redis` packages to be installed"
            )
        self._redis_url = redis_url
        self._queue_name = queue_name
        self._conn = redis.from_url(redis_url)  # type: ignore
        self._queue = rq.Queue(name=queue_name, connection=self._conn)  # type: ignore

    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
        # RQ expects the function to be importable; enqueue call returns a Job
        job = self._queue.enqueue(fn, *args, **kwargs)  # type: ignore
        return job.get_id()

    def status(self, job_id: str) -> Dict[str, Any]:
        try:
            job = rq.job.Job.fetch(job_id, connection=self._conn)  # type: ignore
        except Exception as e:
            raise JobNotFoundError(str(e))
        data: Dict[str, Any] = {
            "id": job.get_id(),
            "status": job.get_status(),
            "created_at": getattr(job, "created_at", None)
            and job.created_at.isoformat(),
            "started_at": getattr(job, "started_at", None)
            and job.started_at.isoformat(),
            "finished_at": getattr(job, "ended_at", None) and job.ended_at.isoformat(),
            "error": None,
            "has_result": hasattr(job, "result"),
            "meta": {},
        }
        if job.exc_info:
            data["error"] = job.exc_info
        return data

    def result(self, job_id: str, timeout: Optional[float] = None) -> Any:
        try:
            job = rq.job.Job.fetch(job_id, connection=self._conn)  # type: ignore
        except Exception:
            raise JobNotFoundError(job_id)
        if job.is_failed:
            raise RuntimeError(job.exc_info)
        if not job.is_finished:
            # blocking behavior: poll until finished or timeout
            import time as _time

            waited = 0.0
            interval = 0.5
            while not job.is_finished:
                if timeout is not None and waited >= timeout:
                    raise TimeoutError("Timeout waiting for job result")
                _time.sleep(interval)
                waited += interval
                job.refresh()  # type: ignore
        return job.result

    def cancel(self, job_id: str) -> bool:
        try:
            job = rq.job.Job.fetch(job_id, connection=self._conn)  # type: ignore
        except Exception:
            return False
        return job.cancel()  # type: ignore

    def list_jobs(self) -> List[Dict[str, Any]]:
        jobs = self._queue.jobs  # type: ignore
        out = []
        for job in jobs:
            out.append(self.status(job.get_id()))
        return out

    def shutdown(self, wait: bool = True):
        # nothing specific to do for RQ backend
        pass

    def cleanup(self, older_than_seconds: int = None) -> int:
        # RQ handles job TTL and result TTL via queue configuration; no-op here
        return 0


class JobManager:
    """High-level manager that delegates to a chosen backend.

    backend: 'auto' (pick RQ if env BIB_USE_RQ=true and RQ available, else in-process),
             'rq', or 'inproc'
    """

    def __init__(
        self,
        backend: Optional[str] = None,
        inproc_workers: int = 4,
        redis_url: str = "redis://localhost:6379/0",
    ):
        choice = backend or os.getenv("BIB_JOB_BACKEND", "auto")
        if choice == "auto":
            if (
                os.getenv("BIB_USE_RQ", "").lower() in ("1", "true", "yes")
                and _RQ_AVAILABLE
            ):
                choice = "rq"
            else:
                choice = "inproc"
        if choice == "rq":
            if not _RQ_AVAILABLE:
                raise RuntimeError(
                    "RQ backend requested but `rq`/`redis` not available"
                )
            self._backend: BaseJobBackend = RQBackend(redis_url=redis_url)
        else:
            self._backend = InProcessBackend(max_workers=inproc_workers)

    # Convenience wrappers
    def submit(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
        return self._backend.submit(fn, *args, **kwargs)

    def submit_analysis(
        self,
        query: str,
        max_results: int = 200,
        sources: Optional[list] = None,
        use_cache: bool = True,
        cache_ttl_hours: int = 24,
    ) -> str:
        """Enqueue an analysis job using the manager's configured backend and return the job id."""
        return self.submit(
            run_analysis_job, query, max_results, sources, use_cache, cache_ttl_hours
        )

    def status(self, job_id: str) -> Dict[str, Any]:
        return self._backend.status(job_id)

    def result(self, job_id: str, timeout: Optional[float] = None) -> Any:
        return self._backend.result(job_id, timeout=timeout)

    def cancel(self, job_id: str) -> bool:
        return self._backend.cancel(job_id)

    def list_jobs(self) -> List[Dict[str, Any]]:
        return self._backend.list_jobs()

    def shutdown(self, wait: bool = True):
        self._backend.shutdown(wait=wait)

    def cleanup(self, older_than_seconds: int = None) -> int:
        return self._backend.cleanup(older_than_seconds=older_than_seconds)


# Module-level default manager (auto picks RQ if BIB_USE_RQ is set and RQ available)
_default_manager: Optional[JobManager] = None
_default_manager_lock = threading.Lock()


def get_default_manager() -> JobManager:
    global _default_manager
    with _default_manager_lock:
        if _default_manager is None:
            _default_manager = JobManager()
        return _default_manager


# Convenience top-level functions
def submit_job(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
    """Submit a job to the default manager. Returns a job ID."""
    mgr = get_default_manager()
    return mgr.submit(fn, *args, **kwargs)


def get_job_info(job_id: str) -> Dict[str, Any]:
    return get_default_manager().status(job_id)


def get_job_result(job_id: str, timeout: Optional[float] = None) -> Any:
    return get_default_manager().result(job_id, timeout=timeout)


def cancel_job(job_id: str) -> bool:
    return get_default_manager().cancel(job_id)


def list_jobs() -> List[Dict[str, Any]]:
    return get_default_manager().list_jobs()


def cleanup_jobs(older_than_seconds: Optional[int] = None) -> int:
    return get_default_manager().cleanup(older_than_seconds=older_than_seconds)


# Example usage in code (for docs):
# job_id = submit_job(analyze_field, "machine learning", max_results_per_source=200, sources=["pubmed"])
# info = get_job_info(job_id)
# result = get_job_result(job_id, timeout=600)
#
# When using RQ backend, ensure the callable you submit is importable by path (module-level
# function or top-level callable), because RQ serializes task references and imports them
# in worker processes.

# ---------------------------
# Artifact store & job helpers (Redis-backed with in-memory fallback)
# ---------------------------
# Store artifact metadata persistently when Redis is available so artifacts
# survive process restarts. If Redis is not available we fall back to an
# in-memory store (suitable for local testing).
#
# The artifact store maps an artifact id (or job id) to a dict with keys:
#  - output_dir: absolute path where artifact files are written
#  - exports_paths: map of export_key -> absolute filepath
#  - download_token: a permanent token for downloads (uuid4 hex)
#  - download_urls: map of export_key -> download URL (constructed by run_analysis_job)
#  - created_at: ISO timestamp
#
# Functions below mirror the previous API (register_job_artifacts, get_job_artifacts,
# clear_job_artifacts, list_job_artifacts) but persist to Redis when available.
try:
    # `redis` may already be imported by the RQ backend import block above; if not,
    # this will still try to import it. We treat absence of redis as a non-fatal condition
    # and simply instantiate an in-memory fallback.
    import redis as _redis  # type: ignore

    _REDIS_AVAILABLE = True
except Exception:
    _redis = None  # type: ignore
    _REDIS_AVAILABLE = False


class ArtifactStore:
    """Abstract artifact storage API."""

    def set(self, artifact_id: str, data: Dict[str, Any]) -> None:
        raise NotImplementedError

    def get(self, artifact_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def delete(self, artifact_id: str) -> bool:
        raise NotImplementedError

    def list_keys(self) -> List[str]:
        raise NotImplementedError


class RedisArtifactStore(ArtifactStore):
    """Redis-backed artifact store (single JSON payload per artifact)."""

    def __init__(self, redis_url: str):
        self._conn = _redis.from_url(redis_url)  # type: ignore

    def _key(self, aid: str) -> str:
        return f"bib:artifact:{aid}"

    def set(self, artifact_id: str, data: Dict[str, Any]) -> None:
        import json as _json

        key = self._key(artifact_id)
        # Ensure only JSON-serializable types are stored
        payload = dict(data)
        # Normalize exports_paths into plain dict (it should already be one)
        payload["exports_paths"] = payload.get("exports_paths", {}) or {}
        self._conn.set(key, _json.dumps(payload))  # type: ignore

    def get(self, artifact_id: str) -> Optional[Dict[str, Any]]:
        import json as _json

        key = self._key(artifact_id)
        raw = self._conn.get(key)  # type: ignore
        if not raw:
            return None
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            return _json.loads(raw)  # type: ignore
        except Exception:
            # Best-effort: if parsing fails, treat as missing
            return None

    def delete(self, artifact_id: str) -> bool:
        key = self._key(artifact_id)
        try:
            self._conn.delete(key)  # type: ignore
            return True
        except Exception:
            return False

    def list_keys(self) -> List[str]:
        # iterate keys like bib:artifact:*
        out: List[str] = []
        try:
            for k in self._conn.scan_iter(match="bib:artifact:*"):  # type: ignore
                if isinstance(k, bytes):
                    k = k.decode("utf-8")
                aid = k.split("bib:artifact:")[-1]
                out.append(aid)
        except Exception:
            pass
        return out


class InMemoryArtifactStore(ArtifactStore):
    """Lightweight memory-backed store for tests / local runs."""

    def __init__(self):
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def set(self, artifact_id: str, data: Dict[str, Any]) -> None:
        with self._lock:
            self._store[artifact_id] = dict(data)

    def get(self, artifact_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            v = self._store.get(artifact_id)
            return dict(v) if v is not None else None

    def delete(self, artifact_id: str) -> bool:
        with self._lock:
            if artifact_id in self._store:
                del self._store[artifact_id]
                return True
            return False

    def list_keys(self) -> List[str]:
        with self._lock:
            return list(self._store.keys())


# Initialize artifact store: prefer Redis when REDIS_URL is configured and the
# redis package is available; otherwise use in-memory fallback.
_ARTIFACT_STORE: ArtifactStore
_REDIS_URL = os.getenv("REDIS_URL") or os.getenv("BIB_REDIS_URL")
if _REDIS_URL and _REDIS_AVAILABLE:
    try:
        _ARTIFACT_STORE = RedisArtifactStore(_REDIS_URL)
    except Exception:
        logger.warning(
            "Could not initialize Redis artifact store; using in-memory fallback"
        )
        _ARTIFACT_STORE = InMemoryArtifactStore()
else:
    _ARTIFACT_STORE = InMemoryArtifactStore()


def register_job_artifacts(job_id: str, artifacts: Dict[str, Any]) -> None:
    """Persist artifact metadata under `job_id` (artifact_id or job id)."""
    if not job_id:
        return
    # Ensure a permanent download token is present (do not overwrite an existing token)
    token = artifacts.get("download_token") or uuid.uuid4().hex
    artifacts = dict(artifacts)
    artifacts["download_token"] = token
    artifacts["created_at"] = artifacts.get("created_at") or _now_iso()
    # Persist via store
    try:
        _ARTIFACT_STORE.set(job_id, artifacts)
    except Exception as e:
        logger.exception("Failed to persist artifact metadata for %s: %s", job_id, e)


def get_job_artifacts(job_id: str) -> Optional[Dict[str, Any]]:
    """Return artifact metadata for the given id (job id or artifact id)."""
    try:
        return _ARTIFACT_STORE.get(job_id)
    except Exception:
        logger.exception("Failed to fetch artifact metadata for %s", job_id)
        return None


def clear_job_artifacts(job_id: str) -> bool:
    """Remove artifact metadata associated with a job id. Returns True on success."""
    try:
        return _ARTIFACT_STORE.delete(job_id)
    except Exception:
        logger.exception("Failed to clear artifact metadata for %s", job_id)
        return False


def list_job_artifacts() -> Dict[str, Dict[str, Any]]:
    """Return a mapping of artifact_id -> metadata for all stored artifacts."""
    out: Dict[str, Dict[str, Any]] = {}
    try:
        for aid in _ARTIFACT_STORE.list_keys():
            meta = _ARTIFACT_STORE.get(aid)
            if meta is not None:
                out[aid] = meta
    except Exception:
        logger.exception("Failed to list job artifacts")
    return out


def run_analysis_job(
    query: str,
    max_results: int = 200,
    sources: Optional[list] = None,
    use_cache: bool = True,
    cache_ttl_hours: int = 24,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Job-friendly wrapper that runs the `analyze_field` pipeline, writes outputs to a
    job-specific output directory and registers artifacts in `_ARTIFACT_REGISTRY`.

    The function will attempt to determine a job id (from the optional `job_id` kwarg,
    or via RQ's `get_current_job()` if RQ is available). When a job id is known, a
    deterministic output directory is created under `BIB_JOB_OUTPUT_DIR` (or the
    system temp dir), which makes it easy for the API to later serve files from that
    directory in a secure fashion.

    Returns the same dict as `analyze_field` with added fields:
      - `_job_output_dir`: path to output dir
      - `artifact_id`: artifact identifier (equal to job_id when available)
      - `download_token`: a random token for secure downloads
      - `exports`: mapping of export keys to download URLs (replacing raw file paths)
      - `exports_paths`: original filesystem paths (kept for local consumption)
    """
    jid = job_id
    # Try to detect RQ job id when available
    if jid is None and _RQ_AVAILABLE:
        try:
            from rq import get_current_job  # type: ignore

            job = get_current_job()
            if job is not None:
                jid = (
                    job.get_id() if hasattr(job, "get_id") else getattr(job, "id", None)
                )
        except Exception:
            pass

    # Determine artifact id (prefer job id when available)
    artifact_id = jid or uuid.uuid4().hex

    # Determine output directory (use artifact_id so it's addressable later)
    base_dir = os.environ.get("BIB_JOB_OUTPUT_DIR") or os.path.join(
        tempfile.gettempdir(), "simple_bib_jobs"
    )
    os.makedirs(base_dir, exist_ok=True)
    out_dir = os.path.join(base_dir, artifact_id)
    os.makedirs(out_dir, exist_ok=True)

    # Run the analysis
    try:
        # Local import to avoid circular imports at module import time
        from bibliometrics import analyze_field

        result = analyze_field(
            query,
            max_results_per_source=max_results,
            sources=sources,
            output_dir=out_dir,
            use_cache=use_cache,
            cache_ttl_hours=cache_ttl_hours,
        )
    except Exception as exc:
        # Register failure metadata so callers can inspect what happened
        meta = {"error": str(exc), "artifact_id": artifact_id, "output_dir": out_dir}
        register_job_artifacts(artifact_id, meta)
        if jid:
            register_job_artifacts(jid, meta)
        raise

    # Prepare exports mapping: keep original paths but expose secure download URLs
    original_exports = result.get("exports", {}) or {}
    result["exports_paths"] = dict(original_exports)

    download_token = uuid.uuid4().hex
    download_urls: Dict[str, str] = {}
    for k, p in original_exports.items():
        try:
            if isinstance(p, str) and p and os.path.exists(p):
                fname = os.path.basename(p)
                url = (
                    f"/artifacts/{artifact_id}/download/{fname}?token={download_token}"
                )
                download_urls[k] = url
            else:
                # Non-file entries or errors are echoed back unchanged
                download_urls[k] = p
        except Exception:
            download_urls[k] = p

    # Register artifact metadata for later serving
    artifacts = {
        "artifact_id": artifact_id,
        "output_dir": out_dir,
        "exports_paths": result["exports_paths"],
        "download_token": download_token,
        "download_urls": download_urls,
    }
    # Register under artifact id and also under job id (if available)
    register_job_artifacts(artifact_id, artifacts)
    if jid:
        register_job_artifacts(jid, artifacts)

    # Update returned result to include artifact info & download URLs
    result["exports"] = download_urls
    result["artifact_id"] = artifact_id
    result["download_token"] = download_token

    # Attach output dir to the returned result for convenience
    result["_job_output_dir"] = out_dir
    return result


__all__ = [
    "BaseJobBackend",
    "InProcessBackend",
    "RQBackend",
    "JobManager",
    "get_default_manager",
    "submit_job",
    "get_job_info",
    "get_job_result",
    "cancel_job",
    "list_jobs",
    "cleanup_jobs",
    "register_job_artifacts",
    "get_job_artifacts",
    "clear_job_artifacts",
    "list_job_artifacts",
    "run_analysis_job",
]
