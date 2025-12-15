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

import io
import json
import os
import tempfile
import time
from datetime import datetime
from typing import Any, Dict, List

# Visualization / data libs
import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components

# Optional heavy import used for filtering and GEXF export in the interactive dashboard.
# Wrapped in a try/except so the app can still run when networkx isn't available.
try:
    import networkx as nx
except Exception:
    nx = None

# Local analysis utilities
from bibliometrics import (
    analyze_field,
    compute_author_metrics,
    publications_to_bibtex_bytes,
    publications_to_csv_bytes,
    publications_to_json_bytes,
    visualize_pyvis,
)

# Optional: LLM summarization via kubectl Groq/Cerebras fallback (bibliometric_crawler)
try:
    from bibliometric_crawler import BibliometricCrawler

    LLM_AVAILABLE = True
except Exception:
    BibliometricCrawler = None
    LLM_AVAILABLE = False


def safe_filename(s: str) -> str:
    s = s.strip().lower().replace(" ", "_")
    s = "".join(ch for ch in s if ch.isalnum() or ch in ("_", "-"))
    return s[:120]


def authors_to_dataframe(authors: List[Any]) -> pd.DataFrame:
    """Convert list of AuthorMetrics dataclasses to a DataFrame for display."""
    rows = []
    for a in authors:
        # AuthorMetrics dataclass has fields name, n_publications, total_citations, h_index, g_index
        rows.append(
            {
                "author": getattr(a, "name", str(a)),
                "n_publications": getattr(a, "n_publications", 0),
                "total_citations": getattr(a, "total_citations", 0),
                "h_index": getattr(a, "h_index", 0),
                "g_index": getattr(a, "g_index", 0),
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(by=["total_citations", "h_index"], ascending=False)
    return df


def display_time_series(time_series: Dict[int, int], forecast: Dict[str, Any]):
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
    with st.spinner("Collecting publications and analyzing..."):
        result = analyze_field(
            query,
            max_results_per_source=max_results,
            sources=sources,
            output_dir=out_dir,
            use_cache=use_cache,
            cache_ttl_hours=cache_ttl_hours,
        )

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
            df_err = pd.DataFrame([{"source": s, "error": e} for s, e in source_errors])
            st.dataframe(df_err)
        except Exception:
            # Fallback: plain list if DataFrame rendering fails
            for s, e in source_errors:
                st.write(f"- {s}: {e}")

    # Top authors table and visualizations
    st.subheader("Top authors")
    top_authors = result.get("top_authors", [])
    if top_authors:
        df_auth = authors_to_dataframe(top_authors)

        # Table + exports in one column, visualizations in the other
        col_table, col_vis = st.columns([2, 3])
        with col_table:
            st.dataframe(df_auth.head(50))
            csv = df_auth.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download top authors CSV", csv, file_name="top_authors.csv"
            )

        with col_vis:
            st.markdown("#### Top authors (by publications)")
            try:
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
    exports = result.get("exports", {})
    gexf_path = exports.get("gexf")
    pyvis_path = exports.get("pyvis")
    graph = result.get("graph")

    if pyvis_path and os.path.exists(pyvis_path):
        st.markdown("**Interactive co-authorship network (pre-generated):**")
        try:
            with open(pyvis_path, "r", encoding="utf-8") as fh:
                html = fh.read()
            components.html(html, height=400, scrolling=True)
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
        min_pubs = st.slider(
            "Minimum publications per author",
            min_value=1,
            max_value=max_n_pubs,
            value=1,
        )
        author_search = st.text_input("Author name contains (filter)", value="")

    with right_col:
        layout_choice = st.selectbox(
            "Layout method",
            options=[
                "Auto (fa2 if available)",
                "ForceAtlas2 (fa2)",
                "Spring (networkx)",
            ],
            index=0,
        )
        layout_map = {
            "Auto (fa2 if available)": "auto",
            "ForceAtlas2 (fa2)": "fa2",
            "Spring (networkx)": "spring",
        }
        fa2_iters = st.slider(
            "ForceAtlas2 iterations", min_value=10, max_value=1000, value=200, step=10
        )
        spring_iters = st.slider(
            "Spring layout iterations", min_value=10, max_value=1000, value=50, step=10
        )
        force_regen = st.checkbox("Always regenerate (ignore cached HTML)", value=False)

    def _filter_graph(G, min_pubs=1, author_query=None):
        """Return a filtered copy of G or None if G is None."""
        if G is None:
            return None
        if nx is None:
            raise RuntimeError(
                "networkx is required for interactive graph filtering (install `networkx`)."
            )
        Gf = G.copy()
        q = (
            author_query.strip().lower()
            if (author_query and author_query.strip())
            else None
        )
        remove = []
        for n, data in Gf.nodes(data=True):
            try:
                if int(data.get("n_pubs", 0) or 0) < int(min_pubs):
                    remove.append(n)
                    continue
            except Exception:
                # if value not parseable, be conservative and keep the node
                pass
            if q:
                name = str(data.get("display_name", n)).lower()
                if q not in name and q not in str(n).lower():
                    remove.append(n)
        if remove:
            Gf.remove_nodes_from(remove)
        # Remove isolates for cleaner visualization
        try:
            isolates = list(nx.isolates(Gf))
            if isolates:
                Gf.remove_nodes_from(isolates)
        except Exception:
            pass
        return Gf

    def _generate_and_write(
        Gf,
        fname_html,
        fname_gexf,
        layout,
        fa2_iterations,
        spring_iterations,
        force=False,
    ):
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
                visualize_pyvis(
                    Gf,
                    fname_html,
                    notebook=False,
                    height="800px",
                    width="100%",
                    layout=layout,
                    fa2_iterations=fa2_iterations,
                    spring_iterations=spring_iterations,
                    seed=42,
                )
            except Exception as e:
                st.error(f"Failed to generate visualization: {e}")
                return None
        return fname_html

    # Button to (re)generate the interactive network
    if st.button("Generate interactive network"):
        if graph is None:
            st.error(
                "Graph not available in results. Make sure the analysis completed successfully and pyvis was available."
            )
        else:
            try:
                filtered = _filter_graph(
                    graph, min_pubs=min_pubs, author_query=author_search
                )
            except Exception as e:
                st.error(str(e))
                filtered = None

            if filtered is None or filtered.number_of_nodes() == 0:
                st.warning(
                    "No nodes remain after filtering. Try reducing the minimum publications threshold or changing your filters."
                )
            else:
                safe_base = safe_filename(query)
                html_name = os.path.join(
                    out_dir,
                    f"{safe_base}_interactive_{layout_map[layout_choice]}_minpubs-{min_pubs}_fa2iter-{fa2_iters}_spriter-{spring_iters}.html",
                )
                gexf_name = os.path.join(out_dir, f"{safe_base}_interactive.gexf")

                # generate (uses cached HTML if present unless force_regen)
                written_html = _generate_and_write(
                    filtered,
                    html_name,
                    gexf_name,
                    layout_map[layout_choice],
                    fa2_iters,
                    spring_iters,
                    force=force_regen,
                )

                if written_html and os.path.exists(written_html):
                    with open(written_html, "r", encoding="utf-8") as fh:
                        html = fh.read()
                    components.html(html, height=800, scrolling=True)
                    # Offer filtered GEXF for download if available
                    try:
                        with open(gexf_name, "rb") as fh:
                            st.download_button(
                                "Download filtered GEXF",
                                fh.read(),
                                file_name=os.path.basename(gexf_name),
                            )
                    except Exception:
                        pass
                    st.success(
                        f"Rendered interactive network (nodes: {filtered.number_of_nodes()}, edges: {filtered.number_of_edges()})"
                    )
                else:
                    st.error(
                        "Failed to generate the interactive visualization. Check logs for details."
                    )

    # LLM summary
    st.subheader("LLM summary")
    if st.button("Generate natural-language summary (LLM)"):
        with st.spinner("Generating summary (LLM)..."):
            summary_text = summarize_with_llm(query, result)
            st.write(summary_text)


def main():
    st.set_page_config(page_title="Simple Bibliometric Explorer", layout="wide")
    st.title("Simple Bibliometric Explorer")
    st.sidebar.header("Query configuration")

    query = st.sidebar.text_input(
        "Search query", value="machine learning in healthcare"
    )
    max_results = st.sidebar.slider(
        "Max results per source", min_value=10, max_value=2000, value=200, step=10
    )
    # default sources
    all_sources = [
        "pubmed",
        "sage",
        "pubchem",
        "gene",
        "genome",
        "scopus",
        "wos",
        "springer",
        "ieee",
        "eric",
    ]
    selected = st.sidebar.multiselect(
        "Sources to search",
        options=all_sources,
        default=["pubmed", "sage", "scopus", "wos"],
    )

    out_root = st.sidebar.text_input("Output root directory", value="analysis_output")
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    out_dir = os.path.join(out_root, f"{safe_filename(query)}_{timestamp}")

    # Cache controls (can be disabled for fresh retrievals)
    use_cache = st.sidebar.checkbox("Use cached search results", value=True)
    cache_ttl_hours = st.sidebar.number_input(
        "Cache TTL (hours)", min_value=1, max_value=168, value=24, step=1
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("Notes:")
    st.sidebar.markdown(
        "- For authoritative citation metrics provide SCOPUS_API_KEY and/or WOS_API_KEY in .env."
    )
    st.sidebar.markdown(
        "- Use the `inspect_groq_models.py` helper to tune the LLM model if needed."
    )
    st.sidebar.markdown(
        "- ForceAtlas2 layout requires `fa2` package (may need compilation on some platforms)."
    )

    run = st.sidebar.button("Run analysis")
    if run:
        # check for keys for selected sources and warn if missing
        missing = []
        if "scopus" in selected and not os.getenv("SCOPUS_API_KEY"):
            missing.append("SCOPUS_API_KEY")
        if "wos" in selected and not os.getenv("WOS_API_KEY"):
            missing.append("WOS_API_KEY")
        if missing:
            st.warning(
                f"Selected sources include keys that are not set in environment: {missing}. Results may be incomplete."
            )

        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception:
            st.error(f"Failed to create output dir: {out_dir}")
            out_dir = tempfile.mkdtemp(prefix="bib_output_")
            st.info(f"Using temporary directory: {out_dir}")

        run_analysis_and_render(
            query,
            selected,
            max_results,
            out_dir,
            use_cache=use_cache,
            cache_ttl_hours=int(cache_ttl_hours),
        )


if __name__ == "__main__":
    main()
