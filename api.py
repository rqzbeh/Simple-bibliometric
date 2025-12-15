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
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Local analysis utilities
from bibliometrics import analyze_field

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
    # create a temporary output directory for this run (caller can download exports later)
    out_dir = os.path.abspath(tempfile.mkdtemp(prefix="bib_api_"))
    logger.info("Starting analysis for query=%s (out_dir=%s)", req.query, out_dir)

    try:
        result = analyze_field(
            req.query,
            max_results_per_source=req.max_results,
            sources=req.sources,
            output_dir=out_dir,
            use_cache=req.use_cache,
            cache_ttl_hours=req.cache_ttl_hours,
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
        return JSONResponse(content=response)
    except Exception as e:
        logger.exception("Failed to build response for query=%s: %s", req.query, e)
        raise HTTPException(status_code=500, detail=f"Failed to serialize result: {e}")


# Simple convenience to run locally with uvicorn
if __name__ == "__main__":
    # Local run: uvicorn must be available in the environment
    import uvicorn

    uvicorn.run(
        "api:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=False
    )
