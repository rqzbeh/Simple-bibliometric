"""
Simple-bibliometric/api.py

A small FastAPI wrapper to expose `analyze_field` as a JSON endpoint.

This provides:
- POST /analyze  -> run an analysis for a query and return a JSON-friendly summary
- GET  /health   -> health check

Notes:
- The endpoint is synchronous and will block until the analysis completes.
- Results are returned in a JSON-friendly form (graph is summarized rather than serialized).
- Generated export file paths (GEXF/pyvis) are returned when available.
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from jobs import (
    get_job_artifacts,
    get_job_info,
    get_job_result,
    run_analysis_job,
    submit_job,
)

logger = logging.getLogger("simple_bibliometric_api")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


class AnalyzeRequest(BaseModel):
    query: str
    sources: Optional[List[str]] = None
    max_results: int = 200
    use_cache: bool = True
    cache_ttl_hours: int = 24


app = FastAPI(
    title="Simple Bibliometric API",
    description="A small wrapper around the Simple-bibliometric analysis pipeline.",
)

# Allow simple CORS (adjust origins in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Serve prebuilt Flutter web UI (if present)
try:
    from fastapi.staticfiles import StaticFiles

    frontend_build_dir = os.path.join(
        os.path.dirname(__file__), "frontend", "flutter_app", "build", "web"
    )
    if os.path.isdir(frontend_build_dir):
        app.mount(
            "/ui",
            StaticFiles(directory=frontend_build_dir, html=True),
            name="frontend_ui",
        )
        logger.info(
            "Mounted prebuilt Flutter web UI at /ui (served from %s)",
            frontend_build_dir,
        )
except Exception as e:
    logger.info("Flutter UI mount skipped or unavailable: %s", e)


# ---------------------------
# Helpers
# ---------------------------
def _serialize_author(a: Any) -> Dict[str, Any]:
    """
    Convert an AuthorMetrics-like object to a JSON-friendly dict.
    Works with simple dataclasses or plain dicts.
    """
    try:
        return {
            "name": getattr(a, "name", str(a)),
            "n_publications": int(getattr(a, "n_publications", 0)),
            "total_citations": int(getattr(a, "total_citations", 0)),
            "h_index": int(getattr(a, "h_index", 0)),
            "g_index": int(getattr(a, "g_index", 0)),
        }
    except Exception:
        # Best-effort fallback
        try:
            return dict(a)
        except Exception:
            return {"name": str(a)}


def _summarize_graph(G) -> Dict[str, Any]:
    """Return a small summary of a networkx graph (node/edge counts, few degrees)."""
    if G is None:
        return {"n_nodes": 0, "n_edges": 0}
    try:
        n_nodes = G.number_of_nodes()
        n_edges = G.number_of_edges()
        degs = sorted((d for _, d in G.degree()), reverse=True)
        top_degrees = degs[:10]
        return {"n_nodes": n_nodes, "n_edges": n_edges, "top_degrees": top_degrees}
    except Exception as e:
        logger.exception("Error summarizing graph: %s", e)
        return {"n_nodes": 0, "n_edges": 0, "error": str(e)}


# ---------------------------
# Endpoints
# ---------------------------
@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze")
def analyze(req: AnalyzeRequest) -> JSONResponse:
    """
    Run the analysis pipeline for the given request.
    Returns a JSON-serializable summary containing:
      - query, n_publications
      - top_authors (list of dicts)
      - time_series, forecast
      - graph_summary (counts + small degree sample)
      - exports (pathnames of generated artifacts when available)
      - source_errors (list of (source, error) tuples if any crawlers failed)
    """
    logger.info("Starting synchronous analysis for query=%s", req.query)

    try:
        # run_analysis_job will create an addressable output directory (artifact)
        # and register it in the job-artifact registry so clients can download files.
        result = run_analysis_job(
            req.query,
            req.max_results,
            req.sources,
            req.use_cache,
            req.cache_ttl_hours,
        )
    except Exception as e:
        logger.exception("Analysis failed for query=%s: %s", req.query, e)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")

    # Build a JSON-friendly summary
    try:
        top_authors = result.get("top_authors", []) or []
        top_authors_serialized = [_serialize_author(a) for a in top_authors]

        graph = result.get("graph")
        graph_summary = _summarize_graph(graph)

        response = {
            "query": result.get("query"),
            "n_publications": int(result.get("n_publications", 0)),
            "top_authors": top_authors_serialized,
            "time_series": result.get("time_series", {}),
            "forecast": result.get("forecast", {}),
            "graph_summary": graph_summary,
            "exports": result.get("exports", {}),
            "source_errors": result.get("source_errors", []),
        }
        # Propagate artifact metadata so clients can download exports immediately
        response.update(
            {
                "artifact_id": result.get("artifact_id"),
                "download_token": result.get("download_token"),
                "exports_paths": result.get("exports_paths", {}),
                "_job_output_dir": result.get("_job_output_dir"),
            }
        )
        return JSONResponse(content=response)
    except Exception as e:
        logger.exception("Failed to build response for query=%s: %s", req.query, e)
        raise HTTPException(status_code=500, detail=f"Failed to serialize result: {e}")


@app.post("/analyze_async")
def analyze_async(req: AnalyzeRequest):
    """
    Enqueue an asynchronous analysis job. Returns a job id immediately.
    Use /jobs/{job_id} to poll status and /jobs/{job_id}/result to fetch the result when finished.
    """
    try:
        job_id = submit_job(
            run_analysis_job,
            req.query,
            req.max_results,
            req.sources,
            req.use_cache,
            req.cache_ttl_hours,
        )
    except Exception as e:
        logger.exception("Failed to enqueue analysis job: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to enqueue job: {e}")
    return JSONResponse(content={"job_id": job_id})


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    """
    Return a summary of the job status (queued / running / finished / failed) and metadata.
    """
    info = get_job_info(job_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse(content=info)


@app.get("/jobs/{job_id}/result")
def job_result(job_id: str):
    """
    Return job result if finished. If not finished, returns 202 with current status.
    """
    info = get_job_info(job_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Job not found")
    status = info.get("status")
    if status != "finished":
        return JSONResponse(status_code=202, content={"status": status})
    try:
        res = get_job_result(job_id)
        artifact_info = {
            "artifact_id": res.get("artifact_id"),
            "download_token": res.get("download_token"),
            "download_urls": res.get("exports", {}),
            "exports_paths": res.get("exports_paths", {}),
        }
        res_with_artifact = dict(res)
        res_with_artifact["artifact_info"] = artifact_info
        return JSONResponse(status_code=200, content=res_with_artifact)
    except Exception as e:
        logger.exception("Failed to fetch job result for %s: %s", job_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to fetch result: {e}")


# Artifact endpoints (files listing + secure download)
@app.get("/artifacts/{artifact_id}/files")
def artifact_files(artifact_id: str, token: Optional[str] = None):
    """
    List files associated with an artifact id.
    If a download token was issued for this artifact, the same token must be provided
    as the `token` query parameter.
    """
    info = get_job_artifacts(artifact_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    expected = info.get("download_token")
    if expected and token != expected:
        raise HTTPException(status_code=403, detail="Invalid download token")

    files = []
    out_dir = info.get("output_dir")
    if out_dir and os.path.exists(out_dir):
        for root, _, fnames in os.walk(out_dir):
            for fname in fnames:
                rel = os.path.relpath(os.path.join(root, fname), out_dir)
                files.append(rel)
    else:
        files = (
            list(info.get("exports_paths", {}).values())
            if info.get("exports_paths")
            else []
        )

    return JSONResponse(content={"artifact_id": artifact_id, "files": files})


@app.get("/artifacts/{artifact_id}/download/{filename}")
def artifact_download(artifact_id: str, filename: str, token: Optional[str] = None):
    """
    Download a file produced by an analysis run (artifact).
    Requires a valid token if one was issued for the artifact.
    """
    info = get_job_artifacts(artifact_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    expected = info.get("download_token")
    if expected and token != expected:
        raise HTTPException(status_code=403, detail="Invalid download token")

    out_dir = info.get("output_dir")
    if not out_dir:
        raise HTTPException(status_code=404, detail="Artifact files not available")

    candidate = os.path.abspath(os.path.join(out_dir, filename))
    if not candidate.startswith(os.path.abspath(out_dir)):
        # Prevent path traversal
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not os.path.exists(candidate):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        candidate, media_type="application/octet-stream", filename=filename
    )


# Simple convenience to run locally with uvicorn
if __name__ == "__main__":
    # Local run: uvicorn must be available in the environment
    import uvicorn

    uvicorn.run(
        "api:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=False
    )
