"""
Simple-bibliometric/bibliometrics.py

Bibliometric analysis utilities:
- collect publications from configured crawlers (PubMed, CrossRef/SAGE, optionally Scopus/WoS/etc. if keys provided)
- deduplicate and normalize publication records
- compute author-level metrics (publication count, total citations, h-index, mean citations)
- build co-authorship graph and export to GEXF/interactive HTML (pyvis)
- compute publications-per-year time series and simple forecasting (linear/OLS, optional statsmodels)
- quick CLI demo for a query to produce summary outputs and files

Design goals:
- Prefer package-based access (biopython, pubchempy, habanero) where available
- Be robust to missing citation counts (use available counts, warn about coverage)
- Provide export formats compatible with VOSviewer / Gephi (GEXF) and interactive HTML (pyvis)
- Provide sensible defaults and graceful degradation if optional libs are absent
"""

from __future__ import annotations

import json
import math
import os
import re
import statistics
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Optional heavy deps are imported lazily or with fallbacks
try:
    import pandas as pd
except Exception:
    pd = None  # type: ignore

try:
    import numpy as np
except Exception:
    np = None  # type: ignore

try:
    import networkx as nx
except Exception:
    nx = None  # type: ignore

try:
    from pyvis.network import Network
except Exception:
    Network = None  # type: ignore

try:
    import community as community_louvain  # python-louvain
except Exception:
    community_louvain = None  # type: ignore

try:
    from sklearn.linear_model import LinearRegression
except Exception:
    LinearRegression = None  # type: ignore

try:
    import statsmodels.api as sm
except Exception:
    sm = None  # type: ignore

# Import crawlers from project
from crawlers import (
    EBSCOCrawler,
    ERICCrawler,
    GeneCrawler,
    GenomeCrawler,
    IEEECrawler,
    PubChemCrawler,
    PubMedCrawler,
    SAGECrawler,
    ScopusCrawler,
    SpringerCrawler,
    WileyCrawler,
    WoSCrawler,
)

# Type aliases
Pub = Dict[str, Any]


# ---------------------------
# Utilities: normalization
# ---------------------------


def _normalize_title(title: str) -> str:
    """Normalize titles for simple deduplication."""
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r"\s+", " ", t)  # collapse whitespace
    t = re.sub(r"[^\w\s]", "", t)  # remove punctuation
    t = t.strip()
    return t


def _normalize_author(name: str) -> str:
    """
    Normalize an author name to 'lastname, initials' (best-effort).
    Many variants exist; this is heuristic for grouping.
    """
    if not name:
        return ""
    s = name.strip()
    # Replace multiple spaces
    s = re.sub(r"\s+", " ", s)
    # If format 'Last, First Middle'
    if "," in s:
        parts = [p.strip() for p in s.split(",")]
        if len(parts) >= 2:
            last = parts[0]
            rest = parts[1]
            initials = "".join(re.findall(r"\b([A-Za-z])", rest)).upper()
            return f"{last.lower()}, {initials}"
    # If format 'First Middle Last'
    parts = s.split()
    if len(parts) == 1:
        return parts[0].lower()
    last = parts[-1]
    rest = parts[:-1]
    initials = "".join([p[0].upper() for p in rest if p])
    return f"{last.lower()}, {initials}"


# ---------------------------
# h-index and related metrics
# ---------------------------


def h_index(citations: Iterable[int]) -> int:
    """Compute the h-index from a list of citations."""
    if citations is None:
        return 0
    arr = sorted([int(c) for c in citations if c is not None], reverse=True)
    h = 0
    for i, c in enumerate(arr, start=1):
        if c >= i:
            h = i
        else:
            break
    return h


def g_index(citations: Iterable[int]) -> int:
    """Compute the g-index as an additional metric."""
    arr = sorted([int(c) for c in citations if c is not None], reverse=True)
    total = 0
    g = 0
    for i, c in enumerate(arr, start=1):
        total += c
        if total >= i * i:
            g = i
        else:
            break
    return g


# ---------------------------
# Data collection & deduplication
# ---------------------------


def collect_publications(
    query: str,
    sources: Optional[List[str]] = None,
    max_results_per_source: int = 200,
    crawlers_to_use: Optional[Dict[str, Any]] = None,
) -> List[Pub]:
    """
    Collect publications from the chosen sources (default: pubmed, sage).
    Each publication is a dict with canonical fields:
      - title, authors (list[str]), year, doi, abstract, citations (int), source, url
    """
    if sources is None:
        sources = ["pubmed", "sage", "pubchem", "gene", "genome"]

    # Use provided crawler instances or create defaults
    crawlers = {}
    if crawlers_to_use:
        crawlers.update(crawlers_to_use)

    # Lazy instantiate missing crawlers from built-in classes
    mapping = {
        "pubmed": PubMedCrawler,
        "sage": SAGECrawler,
        "pubchem": PubChemCrawler,
        "gene": GeneCrawler,
        "genome": GenomeCrawler,
        "scopus": ScopusCrawler,
        "wos": WoSCrawler,
        "springer": SpringerCrawler,
        "ieee": IEEECrawler,
        "eric": ERICCrawler,
        "ebsco": EBSCOCrawler,
        "wiley": WileyCrawler,
    }

    for s in sources:
        if s not in crawlers and s in mapping:
            try:
                crawlers[s] = mapping[s]()
            except Exception:
                # instantiation may fail if API keys / special setup needed
                crawlers[s] = (
                    mapping[s]() if s in ("pubmed", "pubchem", "sage", "gene") else None
                )

    all_pubs: List[Pub] = []
    for s in sources:
        crawler = crawlers.get(s)
        if not crawler:
            continue
        try:
            items = crawler.search(query, max_results=max_results_per_source)
            for item in items:
                # Normalize and ensure canonical keys
                pub = {}
                pub["title"] = item.get("title") or item.get("Title") or ""
                pub["title_norm"] = _normalize_title(pub["title"])
                # Authors: normalize to list of dicts with keys 'name','orcid','affiliation'
                authors = item.get("authors")
                normalized_authors = []
                if authors is None:
                    authors = []
                # Normalize single-string authors lists into a list of strings
                if isinstance(authors, str):
                    authors_list = [
                        a.strip() for a in re.split(r";|,", authors) if a.strip()
                    ]
                else:
                    authors_list = list(authors)
                for author in authors_list:
                    # author may be a dict (from CrossRef/SAGE) or a plain string
                    if isinstance(author, dict):
                        # Try to extract name information robustly
                        name = author.get("name")
                        if not name:
                            name = " ".join(
                                filter(
                                    None,
                                    [author.get("given", ""), author.get("family", "")],
                                )
                            )
                        # Extract ORCID if present (may be a URI)
                        orcid = author.get("ORCID") or author.get("orcid")
                        if isinstance(orcid, str) and "orcid.org" in orcid:
                            orcid = orcid.rstrip("/").split("/")[-1]
                        # Extract affiliations (list of names)
                        affs = []
                        raw_affs = author.get("affiliation") or []
                        for a in raw_affs:
                            if isinstance(a, dict) and a.get("name"):
                                affs.append(a.get("name"))
                            elif isinstance(a, str):
                                affs.append(a)
                        normalized_authors.append(
                            {"name": name, "orcid": orcid, "affiliation": affs}
                        )
                    else:
                        name = str(author).strip()
                        normalized_authors.append(
                            {"name": name, "orcid": None, "affiliation": []}
                        )
                pub["authors"] = normalized_authors
                # Year extraction
                year = (
                    item.get("year")
                    or item.get("pubdate")
                    or item.get("publicationDate", "")
                )
                if isinstance(year, str) and len(year) >= 4 and year[:4].isdigit():
                    pub["year"] = int(year[:4])
                else:
                    try:
                        pub["year"] = int(item.get("year", 0) or 0)
                    except Exception:
                        pub["year"] = 0
                # DOI
                doi = item.get("doi") or item.get("DOI") or ""
                pub["doi"] = doi.strip() if doi else ""
                # Abstract
                pub["abstract"] = item.get("abstract") or item.get("Abstract") or ""
                # Citations: prefer 'citations' key, then CrossRef 'is-referenced-by-count'
                cit = item.get("citations")
                if cit is None:
                    cit = item.get("is-referenced-by-count") or item.get(
                        "is_referenced_by_count"
                    )
                try:
                    pub["citations"] = int(cit) if cit is not None else 0
                except Exception:
                    pub["citations"] = 0
                pub["source"] = s
                pub["url"] = item.get("url", "")
                all_pubs.append(pub)
        except Exception as e:
            # keep going on errors
            print(f"[collect_publications] error crawling {s}: {e}")
            continue

    # Deduplicate
    unique = deduplicate_publications(all_pubs)
    return unique


def deduplicate_publications(publications: List[Pub]) -> List[Pub]:
    """
    Deduplicate publications primarily by DOI, secondarily by normalized title + year.
    Keep the record with the most metadata (longest abstract or greatest citations).
    """
    by_key: Dict[str, Pub] = {}
    for p in publications:
        doi = (p.get("doi") or "").lower().strip()
        if doi:
            key = f"doi:{doi}"
        else:
            key = f"title:{p.get('title_norm', '')}|year:{p.get('year', 0)}"
        existing = by_key.get(key)
        if not existing:
            by_key[key] = p
        else:
            # choose better record: prefer one with DOI, or more citations, or longer abstract
            score_new = (
                (1 if p.get("doi") else 0) * 10000
                + p.get("citations", 0) * 10
                + len(str(p.get("abstract", "")))
            )
            score_old = (
                (1 if existing.get("doi") else 0) * 10000
                + existing.get("citations", 0) * 10
                + len(str(existing.get("abstract", "")))
            )
            if score_new > score_old:
                by_key[key] = p
    return list(by_key.values())


# ---------------------------
# Author metrics and rankings
# ---------------------------


@dataclass
class AuthorMetrics:
    name: str
    n_publications: int
    total_citations: int
    mean_citations: float
    h_index: int
    g_index: int
    publications: List[Pub]


def canonical_author_id(author_entry: Any) -> Tuple[str, str, Optional[str]]:
    """Return a (canonical_id, display_name, orcid) tuple for an author entry.

    - If an ORCID is present and recognizable it becomes the canonical_id (prefixed by 'orcid:').
    - Otherwise we fall back to a normalized name with an optional affiliation token to help disambiguate.
    """
    if isinstance(author_entry, dict):
        name = (author_entry.get("name") or "").strip()
        orcid = author_entry.get("orcid") or author_entry.get("ORCID") or None
        affs = author_entry.get("affiliation") or []
    else:
        name = str(author_entry or "").strip()
        orcid = None
        affs = []

    # Try to normalize ORCID from a URI or direct string
    if orcid and isinstance(orcid, str):
        m = re.search(r"(\d{4}-\d{4}-\d{4}-\d{4})", orcid)
        if m:
            return (f"orcid:{m.group(1)}", name or m.group(1), m.group(1))
        # fallback: use raw orcid if it is non-empty
        return (f"orcid:{orcid}", name or orcid, orcid)

    # No ORCID -> use name + (optional) affiliation token
    name_norm = _normalize_author(name)
    aff_token = ""
    if affs:
        first_aff = str(affs[0]).lower()
        aff_token = re.sub(r"\W+", "", first_aff.split()[0])[:20]
    canonical_id = f"{name_norm}|{aff_token}" if aff_token else f"{name_norm}"
    return (canonical_id, name or canonical_id, None)


def compute_author_metrics(publications: List[Pub]) -> List[AuthorMetrics]:
    """Given a list of publications, compute per-author metrics.

    Uses canonical author IDs (preferring ORCID when available) and returns a
    sorted list of AuthorMetrics (descending by total citations).
    """
    author_to_pubs: Dict[str, List[Pub]] = defaultdict(list)
    author_meta: Dict[
        str, Dict[str, Any]
    ] = {}  # canonical_id -> metadata (display_name, orcid)

    for p in publications:
        authors = p.get("authors") or []
        for a in authors:
            cid, display_name, orcid_val = canonical_author_id(a)
            author_to_pubs[cid].append(p)
            if cid not in author_meta:
                author_meta[cid] = {"display_name": display_name, "orcid": orcid_val}

    results: List[AuthorMetrics] = []
    for cid, pubs in author_to_pubs.items():
        citations_list = [int(pub.get("citations") or 0) for pub in pubs]
        total_cit = sum(citations_list)
        mean_cit = statistics.mean(citations_list) if citations_list else 0.0
        h = h_index(citations_list)
        g = g_index(citations_list)
        display_name = author_meta.get(cid, {}).get("display_name", cid)
        results.append(
            AuthorMetrics(
                name=display_name,
                n_publications=len(pubs),
                total_citations=total_cit,
                mean_citations=mean_cit,
                h_index=h,
                g_index=g,
                publications=pubs,
            )
        )
    results.sort(key=lambda x: x.total_citations, reverse=True)
    return results


# ---------------------------
# Co-authorship graph & exports
# ---------------------------


def build_coauthorship_graph(publications: List[Pub], min_weight: int = 1):
    """
    Construct a co-authorship graph using canonical author IDs (ORCID preferred).
    Nodes are canonical IDs (e.g., 'orcid:0000-0000-0000-0000' or 'lastname, INITS|afftoken').
    Node attributes: display_name, orcid, n_pubs, total_citations, h_index
    Edge attribute: weight = number of coauthored papers
    """
    if nx is None:
        raise RuntimeError("networkx is required to build graphs")

    G = nx.Graph()

    # Build graph by canonical author ids (canonical_author_id returns (cid, display, orcid))
    for pub in publications:
        raw_authors = pub.get("authors") or []
        canonical_authors = []
        for a in raw_authors:
            cid, display, orcid = canonical_author_id(a)
            canonical_authors.append((cid, display, orcid))

        # ensure nodes exist and store basic metadata
        for cid, display, orcid in canonical_authors:
            if not G.has_node(cid):
                G.add_node(cid, label=display, display_name=display, orcid=orcid)

        # add/update edges (increment weight for coauthored papers)
        for (u_cid, _, _), (v_cid, _, _) in itertools.combinations(
            canonical_authors, 2
        ):
            if G.has_edge(u_cid, v_cid):
                G[u_cid][v_cid]["weight"] += 1
            else:
                G.add_edge(u_cid, v_cid, weight=1)

    # Compute per-node metrics directly from the publications (ensures canonical ids are used)
    node_pub_map: Dict[str, List[Pub]] = defaultdict(list)
    for pub in publications:
        raw_authors = pub.get("authors") or []
        for a in raw_authors:
            cid, _, _ = canonical_author_id(a)
            node_pub_map[cid].append(pub)

    for node in list(G.nodes()):
        pubs = node_pub_map.get(node, [])
        citations = [int(p.get("citations") or 0) for p in pubs]
        n_pubs = len(pubs)
        total_citations = sum(citations)
        h = h_index(citations)
        # Attach node attributes: number of pubs, total citations, h-index
        nx.set_node_attributes(G, {node: n_pubs}, "n_pubs")
        nx.set_node_attributes(G, {node: total_citations}, "total_citations")
        nx.set_node_attributes(G, {node: h}, "h_index")

    # remove weak edges if necessary
    to_remove = [
        (u, v) for u, v, d in G.edges(data=True) if d.get("weight", 0) < min_weight
    ]
    for u, v in to_remove:
        G.remove_edge(u, v)

    return G


def detect_communities(G):
    """
    Detect communities (Louvain if available, else greedy modularity communities).
    Returns dict node->community_id and optionally sets 'community' node attribute.
    """
    if nx is None:
        raise RuntimeError("networkx is required")

    partition = {}
    if community_louvain is not None:
        raw = community_louvain.best_partition(G)
        partition = {n: int(c) for n, c in raw.items()}
    else:
        # fallback to greedy modularity (gives communities as sets)
        from networkx.algorithms import community as nxcom

        comms = nxcom.greedy_modularity_communities(G)
        for cid, comset in enumerate(comms):
            for node in comset:
                partition[node] = cid

    nx.set_node_attributes(G, partition, "community")
    return partition


def export_gexf(G, path: str):
    """Export graph to GEXF for Gephi/VOSviewer import."""
    if nx is None:
        raise RuntimeError("networkx is required")
    nx.write_gexf(G, path)


def visualize_pyvis(
    G,
    out_html: str,
    notebook=False,
    height="800px",
    width="100%",
    layout: str = "auto",
    fa2_iterations: int = 200,
    fa2_scaling_ratio: float = 2.0,
    fa2_gravity: float = 1.0,
    spring_k: Optional[float] = None,
    spring_iterations: int = 50,
    seed: Optional[int] = None,
):
    """Create an interactive HTML visualization using pyvis (if available).

    Parameters
    ----------
    G : networkx.Graph
        The co-authorship graph.
    out_html : str
        Output HTML file path that pyvis will write.
    layout : str
        Layout strategy: 'auto' (try ForceAtlas2 then spring), 'fa2' (ForceAtlas2), or 'spring' (networkx spring layout).
    fa2_iterations, fa2_scaling_ratio, fa2_gravity :
        Parameters forwarded to the ForceAtlas2 layout when used.
    spring_k, spring_iterations, seed :
        Parameters forwarded to NetworkX's spring layout when used.

    Returns
    -------
    dict
        A dictionary with keys: 'html' (path), 'layout_used' (string), and 'pos' (node positions mapping) when available.
    """
    if Network is None:
        raise RuntimeError("pyvis is required for interactive visualization")
    if nx is None:
        raise RuntimeError("networkx is required for computing layouts")

    net = Network(height=height, width=width, notebook=notebook)

    pos = None
    layout_used = None

    def _try_forceatlas2(iterations, scalingRatio, gravity):
        try:
            from fa2 import ForceAtlas2
        except Exception:
            return None
        try:
            forceatlas2 = ForceAtlas2(
                outboundAttractionDistribution=False,
                linLogMode=False,
                adjustSizes=False,
                edgeWeightInfluence=1.0,
                jitterTolerance=1.0,
                barnesHutOptimize=True,
                barnesHutTheta=1.2,
                scalingRatio=float(scalingRatio),
                strongGravityMode=False,
                gravity=float(gravity),
                verbose=False,
            )
            return forceatlas2.forceatlas2_networkx_layout(
                G, pos=None, iterations=int(iterations)
            )
        except Exception:
            return None

    # Attempt requested layout; 'auto' will prefer ForceAtlas2 if available
    if layout in ("auto", "fa2"):
        pos = _try_forceatlas2(fa2_iterations, fa2_scaling_ratio, fa2_gravity)
        if pos is not None:
            layout_used = "fa2"
        elif layout == "fa2":
            # explicit request for fa2 but it failed -> fall back to spring and inform user
            print(
                "ForceAtlas2 (fa2) layout requested but not available or failed; falling back to spring layout."
            )

    if pos is None and layout in ("auto", "spring", "fa2"):
        try:
            pos = nx.spring_layout(
                G, k=spring_k, iterations=int(spring_iterations), seed=seed
            )
            layout_used = layout_used or "spring"
        except Exception:
            pos = None

    # Add nodes with size proportional to n_pubs or total_citations and include display_name and community group
    for n, data in G.nodes(data=True):
        display_label = data.get("display_name", n)
        size = max(5, (data.get("n_pubs", 0) * 2) + 5)
        title = f"{display_label}<br>n_pubs: {data.get('n_pubs', 0)}<br>citations: {data.get('total_citations', 0)}"
        group = data.get("community")
        net.add_node(n, label=display_label, title=title, value=size, group=group)

    # Add edges with weights
    for u, v, d in G.edges(data=True):
        net.add_edge(u, v, value=d.get("weight", 1))

    # Apply positions if we computed any (pyvis will use x/y if present)
    if pos:
        for node in net.nodes:
            nid = node["id"]
            p = None
            if nid in pos:
                p = pos[nid]
            elif str(nid) in pos:
                p = pos[str(nid)]
            else:
                # try to match by string equality against any key
                for key in pos.keys():
                    if str(key) == str(nid):
                        p = pos[key]
                        break
            if p is None:
                continue
            try:
                x = float(p[0])
                y = float(p[1])
                node["x"] = x
                node["y"] = y
            except Exception:
                # ignore malformed coordinates
                continue

    # Provide simple physics controls for the user in the generated HTML
    try:
        net.show_buttons(filter_=["physics"])
    except Exception:
        # Not critical; continue without throwing
        pass

    # Write the HTML file
    net.show(out_html)

    return {"html": out_html, "layout_used": layout_used, "pos": pos}


# ---------------------------
# Time series & forecasting
# ---------------------------


def publications_per_year(publications: List[Pub]) -> Dict[int, int]:
    """Return a dict of year->count (only years > 0)."""
    counter = Counter()
    for pub in publications:
        y = pub.get("year") or 0
        if y and isinstance(y, int) and y > 0:
            counter[y] += 1
    # Return an ordered dict-like mapping
    years = dict(sorted(counter.items()))
    return years


def forecast_publications_linear(
    year_count: Dict[int, int], periods: int = 5
) -> Dict[str, Any]:
    """
    Simple forecasting using linear regression over years -> counts.
    Returns a dict with historical series and forecast series (years -> predicted counts).
    Also returns a rough confidence bound using residual std.
    """
    years = sorted(year_count.keys())
    counts = [year_count[y] for y in years]
    if not years:
        return {"history": {}, "forecast": {}, "method": "linear", "notes": "no data"}

    if LinearRegression is None or np is None:
        # fallback: naive forecast (mean)
        avg = sum(counts) / len(counts)
        last_year = max(years)
        forecast = {last_year + i + 1: int(round(avg)) for i in range(periods)}
        return {
            "history": dict(zip(years, counts)),
            "forecast": forecast,
            "method": "naive_mean",
        }

    X = np.array(years).reshape(-1, 1)
    y = np.array(counts)
    model = LinearRegression()
    model.fit(X, y)
    last_year = years[-1]
    future_years = np.array([last_year + i + 1 for i in range(periods)]).reshape(-1, 1)
    preds = model.predict(future_years)
    # compute residual std for rough CI
    residuals = y - model.predict(X)
    std = residuals.std(ddof=1) if len(residuals) > 1 else 0.0
    forecast = {}
    for i, year in enumerate(future_years.flatten()):
        est = max(0.0, preds[i])
        forecast[int(year)] = {
            "predicted": float(est),
            "ci_low": float(max(0.0, est - 1.96 * std)),
            "ci_high": float(est + 1.96 * std),
        }
    return {
        "history": dict(zip(years, counts)),
        "forecast": forecast,
        "method": "linear",
    }


# ---------------------------
# Combined "analysis pipeline"
# ---------------------------


def analyze_field(
    query: str,
    max_results_per_source: int = 500,
    sources: Optional[List[str]] = None,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    High-level pipeline that:
      - collects publications for a query
      - deduplicates and normalizes
      - computes author metrics and top authors
      - constructs co-authorship graph and outputs GEXF & pyvis HTML (if requested)
      - produces publications per year and a simple forecast
    Returns a dict with keys: publications, authors, graph (networkx), exports info, time_series, forecast
    """
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    pubs = collect_publications(
        query, sources=sources, max_results_per_source=max_results_per_source
    )
    authors = compute_author_metrics(pubs)
    top_authors = [a for a in authors][:50]

    # Graph
    G = build_coauthorship_graph(pubs)
    partition = detect_communities(G)

    exports = {}
    if output_dir:
        gexf_path = os.path.join(
            output_dir, f"{query.replace(' ', '_')}_coauthorship.gexf"
        )
        try:
            export_gexf(G, gexf_path)
            exports["gexf"] = gexf_path
        except Exception as e:
            exports["gexf_error"] = str(e)
        # pyvis interactive
        if Network is not None:
            html_path = os.path.join(
                output_dir, f"{query.replace(' ', '_')}_coauthorship.html"
            )
            try:
                visualize_pyvis(G, html_path)
                exports["pyvis"] = html_path
            except Exception as e:
                exports["pyvis_error"] = str(e)

    ts = publications_per_year(pubs)
    forecast = forecast_publications_linear(ts, periods=5)

    return {
        "query": query,
        "n_publications": len(pubs),
        "publications": pubs,
        "top_authors": top_authors,
        "graph": G,
        "communities": partition,
        "exports": exports,
        "time_series": ts,
        "forecast": forecast,
    }


# ---------------------------
# CLI demo
# ---------------------------
def _print_top_authors(authors: List[AuthorMetrics], top_n: int = 10):
    print(f"Top {top_n} authors:")
    for i, a in enumerate(authors[:top_n], start=1):
        print(
            f"{i}. {a.name} | pubs={a.n_publications} | citations={a.total_citations} | h={a.h_index} | g={a.g_index}"
        )


def _demo_main():
    import argparse

    parser = argparse.ArgumentParser(description="Bibliometrics demo")
    parser.add_argument("--query", "-q", required=True)
    parser.add_argument("--max-results", "-m", type=int, default=200)
    parser.add_argument("--out", "-o", default="analysis_output")
    args = parser.parse_args()

    print("Collecting and analyzing:", args.query)
    res = analyze_field(
        args.query, max_results_per_source=args.max_results, output_dir=args.out
    )
    print(f"Collected {res['n_publications']} publications")
    _print_top_authors(res["top_authors"], top_n=20)
    print("Exports:", res["exports"])
    print(
        "Publications per year (recent):",
        sorted(res["time_series"].items(), reverse=True)[:10],
    )
    print("Forecast (next years):")
    for year, pred in res["forecast"]["forecast"].items():
        print(f"  {year}: {pred}")


if __name__ == "__main__":  # run demo
    try:
        _demo_main()
    except Exception as exc:
        print("Demo failed:", exc)
        traceback.print_exc()
