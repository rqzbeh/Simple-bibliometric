"""
Streamlit dashboard for interactive bibliometric analysis.

Usage:
    streamlit run app.py

This app uses the project's analysis pipeline to:
 - fetch publications for a query (PubMed/CrossRef by default; Scopus/WoS if keys available)
 - compute author-level metrics (publications, citations, h-index)
 - build and visualize co-authorship networks (GEXF export + interactive pyvis HTML)
 - plot publication trends and simple forecasts

Notes:
 - This script will attempt to use available data providers. For authoritative
   citation/h-index numbers, provide SCOPUS_API_KEY and/or WOS_API_KEY in your .env.
 - ForceAtlas2 layout is used when the 'fa2' package is installed; otherwise we
   fall back to a spring layout.
 - To enable Cerebras fallback for LLM-based summaries, set CEREBRAS_API_KEY in `.env`.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, List

# Visualization / data libs
try:
    import pandas as pd
except Exception:
    pd = None  # type: ignore

try:
    import plotly.express as px
except Exception:
    px = None  # type: ignore

import streamlit as st
import streamlit.components.v1 as components

# Optional heavy import used for filtering and GEXF export in the interactive dashboard.
# Wrapped in a try/except so the app can still run when networkx isn't available.
try:
    import networkx as nx
except Exception:
    nx = None  # type: ignore

# Local analysis utilities
from bibliometrics import (
    analyze_field,
    publications_to_bibtex_bytes,
    publications_to_csv_bytes,
    publications_to_json_bytes,
    visualize_pyvis,
    compute_author_metrics,
)

# Optional: LLM summarization via kubectl Groq/Cerebras fallback (bibliometric_crawler)
try:
    from bibliometric_crawler import BibliometricCrawler

    LLM_AVAILABLE = True
except Exception:
    BibliometricCrawler = None  # type: ignore
    LLM_AVAILABLE = False


def safe_filename(s: str) -> str:
    s = s.strip().lower().replace(" ", "_")
    s = "".join(ch for ch in s if ch.isalnum() or ch in ("_", "-"))
    return s[:120]


def authors_to_dataframe(authors: List[Any]):
    """Convert list of AuthorMetrics dataclasses to a DataFrame (if pandas available) or a list.

    Use a local import to avoid NameErrors/UnboundLocalError when Streamlit reloads modules.
    """
    rows = []
    for a in authors:
        rows.append(
            {
                "author": getattr(a, "name", str(a)),
                "n_publications": getattr(a, "n_publications", 0),
                "total_citations": getattr(a, "total_citations", 0),
                "h_index": getattr(a, "h_index", 0),
                "g_index": getattr(a, "g_index", 0),
            }
        )

    # Prefer a local import to avoid relying on module-level `pd` binding which can
    # be shadowed during interactive reloads (Streamlit dev server behavior).
    try:
        import pandas as _pd  # type: ignore

        df = _pd.DataFrame(rows)
    except Exception:
        return rows

    if not df.empty:
        df = df.sort_values(by=["total_citations", "h_index"], ascending=False)
    return df


def display_time_series(time_series: Dict[int, int], forecast: Dict[str, Any]):
    if px is None:
        st.write("Plotting not available (plotly not installed).")
        return

    df_hist = pd.DataFrame(
        {"year": list(time_series.keys()), "count": list(time_series.values())}
    ).sort_values("year")
    fig = px.line(df_hist, x="year", y="count", title="Publications per year (history)")
    st.plotly_chart(fig, use_container_width=True)

    # Forecast: expected structure is a dict with years -> {predicted, ci_low, ci_high} or simple numeric
    if forecast and isinstance(forecast.get("forecast"), dict):
        fc = forecast["forecast"]
        fc_rows = []
        for y, val in fc.items():
            if isinstance(val, dict):
                fc_rows.append(
                    {
                        "year": int(y),
                        "predicted": float(val.get("predicted", 0)),
                        "ci_low": float(val.get("ci_low", 0)),
                        "ci_high": float(val.get("ci_high", 0)),
                    }
                )
            else:
                # older style: numeric
                fc_rows.append({"year": int(y), "predicted": float(val)})
        if fc_rows:
            df_fc = pd.DataFrame(fc_rows).sort_values("year")
            fig2 = px.line(
                df_fc, x="year", y="predicted", title="Forecast (next years)"
            )
            # also show history points
            st.plotly_chart(fig2, use_container_width=True)
            st.dataframe(df_fc)


def summarize_with_llm(query: str, result_summary: Dict[str, Any]) -> str:
    """
    Use Groq/Cerebras via BibliometricCrawler to produce a natural-language summary.
    This will call external LLM services; ensure API keys are configured.
    """
    if not LLM_AVAILABLE:
        return "LLM summarization not available in this environment."

    # We'll instantiate the crawler (it will manage Groq/Cerebras fallback)
    try:
        bc = BibliometricCrawler()
    except Exception as e:
        return f"Could not initialize LLM client: {e}"

    # Provide a concise, structured prompt with the results
    top_authors = result_summary.get("top_authors", [])[:10]
    top_authors_text = [
        {
            "author": getattr(a, "name", str(a)),
            "pubs": getattr(a, "n_publications", 0),
            "citations": getattr(a, "total_citations", 0),
            "h_index": getattr(a, "h_index", 0),
        }
        for a in top_authors
    ]
    msg = f"""Given the following bibliometric analysis for query: "{query}":

Top authors:
{json.dumps(top_authors_text, indent=2)}

Provide a concise natural-language summary (3-5 sentences) describing:
- The main research trends visible
- The top author(s) and why they are influential (metrics referenced)
- Any notable changes in publication volume over time
Return a brief paragraph summary."""

    system_prompt = "You are a bibliometric analyst. Summarize the data succinctly."
    try:
        response = bc.groq_client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": msg},
            ],
            model=bc.groq_model,
            temperature=0.3,
            max_tokens=250,
        )
        text = response.choices[0].message.content
        return text
    except Exception as e:
        # Try Cerebras fallback if available (BibliometricCrawler also handles fallback on analyze path,
        # but for direct calls we surface an explanatory error)
        return f"LLM request failed: {e}"


def run_analysis_and_render(
    query: str,
    sources: List[str],
    max_results: int,
    out_dir: str,
    use_cache: bool = True,
    cache_ttl_hours: int = 24,
):
    st.info("Starting analysis. This may take a few minutes for large queries.")
    # Option: use AI-driven query analysis and filtering pipeline (Groq + optional AI fallbacks)
    use_ai = False
    try:
        use_ai = LLM_AVAILABLE and st.checkbox("Use AI (Groq) for analysis & filtering", value=bool(os.getenv("GROQ_API_KEY")))
    except Exception:
        use_ai = False

    with st.spinner("Collecting publications and analyzing..."):
        if use_ai:
            # Use AI pipeline
            try:
                bc = BibliometricCrawler()
            except Exception as e:
                st.error(f"Could not initialize AI client: {e}")
                return

            try:
                processed = bc.process_query(query, max_results)
            except Exception as e:
                st.error(f"AI analysis failed: {e}")
                return

            # Flatten raw results into publications list and de-duplicate by normalized title
            raw = processed.get("raw_results", {})
            pubs = []
            seen = set()
            from bibliometrics import _normalize_title

            for db_name, items in raw.items():
                for p in items:
                    t = _normalize_title(p.get("title", ""))
                    if t in seen:
                        continue
                    seen.add(t)
                    pubs.append(p)

            result = {
                "query": query,
                "n_publications": processed.get("total_results", len(pubs)),
                "publications": pubs,
                "top_authors": [],
                "graph": None,
                "exports": {},
                "time_series": {},
                "forecast": {},
                "filtering_guidance": processed.get("filtering_guidance"),
                "analysis_provider": processed.get("analysis_provider"),
                "filtering_provider": processed.get("filtering_provider"),
            }

            # Compute authors, graph and basic stats from flattened pubs
            try:
                authors = compute_author_metrics(pubs)
                result["top_authors"] = authors
            except Exception:
                result["top_authors"] = []
            try:
                from bibliometrics import build_coauthorship_graph, publications_per_year, forecast_publications_linear

                G = build_coauthorship_graph(pubs)
                result["graph"] = G
                result["time_series"] = publications_per_year(pubs)
                result["forecast"] = forecast_publications_linear(result["time_series"], periods=5)
            except Exception:
                pass
        else:
            result = analyze_field(
                query,
                max_results_per_source=max_results,
                sources=sources,
                output_dir=out_dir,
                use_cache=use_cache,
                cache_ttl_hours=cache_ttl_hours,
            )

    # Ensure graph and exports are initialized early so later blocks can reference them
    graph = result.get("graph")
    exports = result.get("exports", {})

    # Display AI provider info when available
    ap = result.get("analysis_provider")
    fp = result.get("filtering_provider")
    if ap or fp:
        st.subheader("AI Providers (traceability)")
        if ap:
            st.markdown(f"- Analysis provider: **{ap.get('provider')}** (model: `{ap.get('model')}`)")
        if fp:
            st.markdown(f"- Filtering provider: **{fp.get('provider')}** (model: `{fp.get('model')}`)")

    # Display summary metrics
    st.subheader("Summary")
    st.markdown(f"- Publications collected: **{result.get('n_publications', 0)}**")
    st.markdown(f"- Outputs written to: **{out_dir}**")

    # Show per-source crawl errors (if any) so users can inspect which sources failed
    source_errors = result.get("source_errors", [])
    if source_errors:
        st.subheader("Source crawl errors")
        st.warning(
            "Some sources failed during crawling. Check details below and consider re-running with caching disabled or increasing retries."
        )
        try:
            # Present errors in a tidy table for easier inspection
            if pd is not None:
                df_err = pd.DataFrame(
                    [{"source": s, "error": e} for s, e in source_errors]
                )
                st.dataframe(df_err)
            else:
                for s, e in source_errors:
                    st.write(f"- {s}: {e}")
        except Exception:
            # Fallback: plain list if DataFrame rendering fails
            for s, e in source_errors:
                st.write(f"- {s}: {e}")

    # ---- Interactive exploration controls ----
    st.markdown("**Interactive exploration**")
    left_col, right_col = st.columns([2, 1])

    # Determine a reasonable upper bound for the minimum-publications slider
    max_n_pubs = 1
    if graph is not None:
        try:
            max_n_pubs = max(
                (int(d.get("n_pubs", 0) or 0) for _, d in graph.nodes(data=True)),
                default=1,
            )
            max_n_pubs = max(1, max_n_pubs)
        except Exception:
            max_n_pubs = 1

    with left_col:
        slider_max = max(2, int(max_n_pubs))
        min_pubs = st.slider(
            "Minimum publications per author",
            min_value=1,
            max_value=slider_max,
            value=1,
            key="min_pubs_slider_top",
        )
        _author_search = st.text_input("Author name contains (filter)", value="", key="author_search_text_top")

    with right_col:
        _layout_choice = st.selectbox(
            "Layout method",
            options=[
                "Auto (fa2 if available)",
                "ForceAtlas2 (fa2)",
                "Spring (networkx)",
            ],
            index=0,
            key="layout_select_top",
        )
        _layout_map = {
            "Auto (fa2 if available)": "auto",
            "ForceAtlas2 (fa2)": "fa2",
            "Spring (networkx)": "spring",
        }
        _fa2_iters = st.slider(
            "ForceAtlas2 iterations", min_value=10, max_value=1000, value=200, step=10, key="fa2_iters_top"
        )

    # Top authors table and visualizations
    st.subheader("Top authors")
    top_authors = result.get("top_authors", [])

    # Apply interactive filters to top authors
    if top_authors:
        filtered_authors = []
        for a in top_authors:
            try:
                n_pubs = int(getattr(a, "n_publications", getattr(a, "n_pubs", 0)) or 0)
            except Exception:
                n_pubs = 0
            name = str(getattr(a, "name", a))
            if n_pubs >= min_pubs and (_author_search.strip().lower() in name.lower()):
                filtered_authors.append(a)

        df_auth = authors_to_dataframe(filtered_authors)

        # Table + exports in one column, visualizations in the other
        col_table, col_vis = st.columns([2, 3])
        with col_table:
            if hasattr(df_auth, "to_csv"):
                csv = df_auth.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "Download top authors CSV", csv, file_name="top_authors.csv"
                )
            st.dataframe(df_auth.head(50))

        with col_vis:
            st.markdown("#### Top authors (by publications)")
            try:
                if px is not None:
                    fig_pub = px.bar(
                        df_auth.head(20),
                        x="author",
                        y="n_publications",
                        title="Top authors (publications)",
                    )
                    st.plotly_chart(fig_pub, use_container_width=True)
            except Exception as e:
                st.warning(f"Could not render publications chart: {e}")

            st.markdown("#### Top authors (by citations)")
            try:
                if px is not None:
                    fig_cit = px.bar(
                        df_auth.head(20),
                        x="author",
                        y="total_citations",
                        title="Top authors (citations)",
                    )
                    st.plotly_chart(fig_cit, use_container_width=True)
            except Exception as e:
                st.warning(f"Could not render citations chart: {e}")

    else:
        st.write("No authors found for this query.")

    # Network diagnostics: degree distribution
    if graph is not None and nx is not None:
        st.subheader("Network diagnostics")
        try:
            degrees = [d for _, d in graph.degree()]
            if px is not None:
                fig_deg = px.histogram(x=degrees, nbins=30, title="Degree distribution")
                st.plotly_chart(fig_deg, use_container_width=True)
        except Exception as e:
            st.warning(f"Could not compute network diagnostics: {e}")

    # Ego-network viewer
    if graph is not None:
        st.subheader("Ego network viewer")
        try:
            # Candidate list from top authors and graph node display names
            candidates = []
            for a in top_authors:
                name = getattr(a, "name", str(a))
                if name and name not in candidates:
                    candidates.append(name)
            for n, d in graph.nodes(data=True):
                display = d.get("display_name", n)
                if display not in candidates:
                    candidates.append(display)

            selected_author = st.selectbox("Select author to focus", options=candidates)
            if st.button("Show ego network"):
                # Attempt to find the matching node id
                target = None
                for n, d in graph.nodes(data=True):
                    if (
                        str(d.get("display_name", n)) == selected_author
                        or str(n) == selected_author
                    ):
                        target = n
                        break
                if target is None:
                    st.warning("Author not found in the co-authorship network.")
                else:
                    try:
                        ego = nx.ego_graph(graph, target, radius=1)
                        ego_html = os.path.join(
                            out_dir,
                            f"{safe_filename(query)}_ego_{safe_filename(selected_author)}.html",
                        )
                        visualize_pyvis(ego, ego_html)
                        with open(ego_html, "r", encoding="utf-8") as fh:
                            components.html(fh.read(), height=600, scrolling=True)
                    except Exception as e:
                        st.error(f"Could not render ego network: {e}")
        except Exception as e:
            st.warning(f"Ego network viewer unavailable: {e}")

    # Exports for publications
    st.subheader("Exports")
    publications = result.get("publications", [])
    if publications:
        pubs_csv = publications_to_csv_bytes(publications)
        st.download_button(
            "Download publications (CSV)", pubs_csv, file_name="publications.csv"
        )
        pubs_json = publications_to_json_bytes(publications)
        st.download_button(
            "Download publications (JSON)", pubs_json, file_name="publications.json"
        )
        pubs_bib = publications_to_bibtex_bytes(publications)
        st.download_button(
            "Download publications (BibTeX)", pubs_bib, file_name="publications.bib"
        )
    else:
        st.write("No publications available to export.")

    # Time series & forecast
    st.subheader("Publication trend and forecast")
    display_time_series(result.get("time_series", {}), result.get("forecast", {}))

    # Network visualization (pre-generated if available)
    st.subheader("Co-authorship network")
    # note: `exports` and `graph` are already prepared above
    _gexf_path = exports.get("gexf")
    pyvis_path = exports.get("pyvis")

    if pyvis_path and os.path.exists(pyvis_path):
        st.markdown("**Interactive co-authorship network (pre-generated):**")
        try:
            with open(pyvis_path, "r", encoding="utf-8") as fh:
                html = fh.read()
            components.html(html, height=600, scrolling=True)
        except Exception as e:
            st.warning(f"Could not load pre-generated visualization: {e}")
        st.markdown(
            "You can also interactively filter and re-generate a network below for exploration."
        )
    else:
        st.info(
            "No pre-generated pyvis visualization available. Use the controls below to generate one interactively (requires `pyvis` and optionally `fa2`)."
        )

    # ---- Interactive exploration controls ----
    st.markdown("**Interactive exploration**")
    left_col, right_col = st.columns([2, 1])

    # Determine a reasonable upper bound for the minimum-publications slider
    max_n_pubs = 1
    if graph is not None:
        try:
            max_n_pubs = max(
                (int(d.get("n_pubs", 0) or 0) for _, d in graph.nodes(data=True)),
                default=1,
            )
            max_n_pubs = max(1, max_n_pubs)
        except Exception:
            max_n_pubs = 1

    with left_col:
        slider_max = max(2, int(max_n_pubs))
        min_pubs = st.slider(
            "Minimum publications per author",
            min_value=1,
            max_value=slider_max,
            value=1,
            key="min_pubs_slider_bottom",
        )
        _author_search = st.text_input("Author name contains (filter)", value="", key="author_search_text_bottom")

    with right_col:
        _layout_choice = st.selectbox(
            "Layout method",
            options=[
                "Auto (fa2 if available)",
                "ForceAtlas2 (fa2)",
                "Spring (networkx)",
            ],
            index=0,
            key="layout_select_bottom",
        )
        _layout_map = {
            "Auto (fa2 if available)": "auto",
            "ForceAtlas2 (fa2)": "fa2",
            "Spring (networkx)": "spring",
        }
        _fa2_iters = st.slider(
            "ForceAtlas2 iterations", min_value=10, max_value=1000, value=200, step=10, key="fa2_iters_bottom"
        )

    def _generate_and_write(Gf, out_dir, fname_gexf, fname_html, layout_choice, fa2_iters, force=False):
        """Write a GEXF and generate a pyvis HTML (cached by filename)."""
        os.makedirs(out_dir, exist_ok=True)
        # Write GEXF (for download) where possible
        try:
            if Gf is not None:
                nx.write_gexf(Gf, fname_gexf)
        except Exception as e:
            st.warning(f"Could not write GEXF: {e}")
        # Generate HTML if needed (or forced)
        need_gen = force or not os.path.exists(fname_html)
        if need_gen:
            try:
                visualize_pyvis(Gf, fname_html, layout=layout_choice, fa2_iterations=fa2_iters)
            except Exception as e:
                st.warning(f"Could not generate HTML visualization: {e}")
                return None
        return fname_html if os.path.exists(fname_html) else None

    # Apply filters to the graph and regenerate visualization if button is clicked
    if graph is not None and nx is not None and query and out_dir:
        if st.button("Generate filtered network", key="gen_filtered_network"):
            try:
                # Filter graph based on min_pubs
                filtered_graph = graph.copy()
                nodes_to_remove = []
                for n, d in filtered_graph.nodes(data=True):
                    n_pubs_node = int(d.get("n_pubs", 0) or 0)
                    display_name = d.get("display_name", str(n))
                    # Apply filters
                    if n_pubs_node < min_pubs:
                        nodes_to_remove.append(n)
                    elif _author_search.strip() and _author_search.strip().lower() not in display_name.lower():
                        nodes_to_remove.append(n)
                
                filtered_graph.remove_nodes_from(nodes_to_remove)
                
                if filtered_graph.number_of_nodes() == 0:
                    st.warning("No authors match the current filter criteria.")
                else:
                    # Generate filtered visualization
                    layout_choice = _layout_map.get(_layout_choice, "auto")
                    safe_query = query.replace(' ', '_').replace('/', '_').replace('\\', '_')
                    filtered_html = os.path.join(
                        out_dir,
                        f"{safe_query}_filtered_{min_pubs}pubs.html"
                    )
                    filtered_gexf = os.path.join(
                        out_dir,
                        f"{safe_query}_filtered_{min_pubs}pubs.gexf"
                    )
                    
                    result_html = _generate_and_write(
                        filtered_graph, out_dir, filtered_gexf, filtered_html, 
                        layout_choice, _fa2_iters, force=True
                    )
                    
                    if result_html and os.path.exists(result_html):
                        st.success(f"Generated filtered network with {filtered_graph.number_of_nodes()} authors and {filtered_graph.number_of_edges()} collaborations")
                        with open(result_html, "r", encoding="utf-8") as fh:
                            components.html(fh.read(), height=600, scrolling=True)
                        
                        # Offer download
                        with open(filtered_gexf, "rb") as f:
                            st.download_button(
                                "Download filtered network (GEXF)",
                                f.read(),
                                file_name=f"{query.replace(' ', '_')}_filtered.gexf"
                            )
            except Exception as e:
                st.error(f"Failed to generate filtered network: {e}")
    else:
        st.info("No network graph available. Run an analysis first.")


def main():
    st.title("Simple Bibliometric Explorer")
    st.sidebar.header("Query")
    query = st.sidebar.text_input("Enter a search query", "")
    sources = st.sidebar.multiselect(
        "Sources",
        options=["pubmed", "sage", "pubchem", "gene", "genome", "scopus", "wos"],
        default=["pubmed", "sage"],
    )
    max_results = st.sidebar.slider(
        "Max results per source", min_value=10, max_value=1000, value=200, step=10
    )
    use_cache = st.sidebar.checkbox("Use cached search results", value=True)
    cache_ttl_hours = st.sidebar.number_input(
        "Cache TTL (hours)", min_value=1, max_value=168, value=24
    )
    outdir_override = st.sidebar.text_input("Output directory (optional)", value="")

    if st.sidebar.button("Run analysis") and query.strip():
        out_dir = outdir_override or os.path.abspath(
            tempfile.mkdtemp(prefix="bib_streamlit_")
        )
        run_analysis_and_render(
            query,
            sources,
            max_results,
            out_dir,
            use_cache=use_cache,
            cache_ttl_hours=cache_ttl_hours,
        )


if __name__ == "__main__":
    main()
