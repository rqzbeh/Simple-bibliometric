# Simple-bibliometric

A bibliometric data crawler powered by Groq AI that searches across multiple academic databases and intelligently filters and normalizes results.

## Features

- **AI-Powered Query Analysis**: Uses Groq AI to understand user queries and determine optimal search strategies
- **Multi-Database Support**: Crawls data from 13 academic sources with **actual API implementations**:
  - Web of Science (WoS) - Clarivate API
  - Scopus - Elsevier API
  - ScienceDirect - Elsevier API
  - PubMed - NCBI E-utilities
  - PubChem - NCBI PUG REST API
  - NCBI Gene - NCBI E-utilities
  - NCBI Genome - NCBI E-utilities
  - SAGE Journals - CrossRef API
  - IEEE Xplore - IEEE API
  - ERIC - IES API
  - Springer - Springer Nature API
  - EBSCO - EBSCO API (requires OAuth)
  - Wiley Online Library - Wiley TDM API

- **Intelligent Data Filtering**: AI automatically identifies and combines similar results (e.g., "data mining" and "data-mining")
- **Result Normalization**: Deduplicates entries across databases
- **Rate Limiting**: Respects API rate limits for each source
- **Standardized Output**: All crawlers return data in a consistent format
- **Extensible Architecture**: Easy to add new data sources

## Installation

1. Clone the repository:
```bash
git clone https://github.com/rqzbeh/Simple-bibliometric.git
cd Simple-bibliometric
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up your API keys:
```bash
cp .env.example .env
# Edit .env and add your API keys
```

## Configuration

Create a `.env` file with your API keys:

```env
# Required
GROQ_API_KEY=your_groq_api_key_here

# Optional - Add as you obtain them
WOS_API_KEY=your_wos_api_key
SCOPUS_API_KEY=your_scopus_api_key
SCIENCEDIRECT_API_KEY=your_sciencedirect_api_key
# ... etc
```

Get your Groq API key from: https://console.groq.com/

## Usage

### Command Line Interface

Run the interactive CLI:

```bash
python bibliometric_crawler.py
```

Then enter your research query:
```
> machine learning in healthcare
```

### Interactive Dashboard (Streamlit)

For a guided, interactive experience (visualization, layout tuning, filtering and export), use the Streamlit dashboard.

1. Install dependencies (including optional extras for better layouts / visuals):
```bash
pip install -r requirements.txt
# Optional: ForceAtlas2 layout (recommended for large networks)
pip install fa2
```

Note: On some platforms `fa2` may require compilation support (C compiler / build tools). If `fa2` cannot be installed, the dashboard will automatically fall back to NetworkX's spring layout.

2. Start the Streamlit app from the project root:
```bash
streamlit run app.py
```
or explicitly:
```bash
streamlit run Simple-bibliometric/app.py
```

3. In the dashboard:
- Enter a query in the sidebar and click "Run analysis" to fetch publications and compute author metrics.
- Inspect top authors, publication trends, and forecasts.
- Use the "Interactive exploration" controls to:
  - Set a minimum-publications threshold to filter authors,
  - Search for author names (substring match),
  - Choose a layout method ("Auto" will use ForceAtlas2 if installed; otherwise it falls back to spring),
  - Adjust iteration counts for ForceAtlas2 / spring layouts,
  - Click "Generate interactive network" to render an embedded pyvis visualization.
- Download filtered GEXF files for use in Gephi or VOSviewer.

- Exports & downloads:
  - Use the "Exports" section to download the full publications list as CSV, JSON, or BibTeX.
  - Download the top authors table as CSV (available next to the table).
  - Export filtered graphs in GEXF format for import into Gephi / VOSviewer.

- Caching & performance:
  - Use the "Use cached search results" checkbox in the sidebar to avoid duplicate API calls for repeated queries (this reduces API usage and speeds up exploration).
  - Set "Cache TTL (hours)" to control how long cached results are considered fresh (default: 24 hours).
  - To clear the cache manually, delete files in the `.cache/` directory, or call `cache_utils.clear_cache()` programmatically.

### API Server (FastAPI)

A small FastAPI-based API is included to make the analysis pipeline available to external UIs (e.g., a Flutter app) and other programmatic consumers.

Quick start:
```bash
# install dependencies (additions include fastapi and uvicorn)
pip install -r requirements.txt

# run the API server locally
uvicorn api:app --reload --port 8000
```

Synchronous analysis (simple):
- URL: `http://localhost:8000/analyze`
- Method: POST
- Body (JSON):
```json
{
  "query": "machine learning in healthcare",
  "max_results": 200,
  "sources": ["pubmed", "sage"],
  "use_cache": true,
  "cache_ttl_hours": 24
}
```
- Response (JSON) — a summarized, JSON-friendly payload:
  - `n_publications`: integer
  - `top_authors`: list of author summaries (name, n_publications, total_citations, h_index)
  - `time_series`, `forecast`: timeseries and forecast objects
  - `graph_summary`: lightweight graph info (n_nodes, n_edges, sample degrees)
  - `exports`: paths to generated artifacts (GEXF/pyvis HTML) when available
  - `source_errors`: list of (source, error) tuples for any sources that failed during crawling

Asynchronous jobs (recommended for long-running analyses):
To avoid blocking HTTP responses for heavy/long analyses, a background job queue is available. Use the async endpoints to enqueue work and poll for completion.

1) Enqueue an async analysis:
- POST `http://localhost:8000/analyze_async`
- Request body: same JSON shape as `/analyze` (query, max_results, sources, use_cache, cache_ttl_hours)
- Response:
```json
{ "job_id": "abcdef123456..." }
```

Example:
```bash
curl -X POST http://localhost:8000/analyze_async \
  -H "Content-Type: application/json" \
  -d '{"query":"machine learning in healthcare","max_results":200}'
```

2) Poll job status:
- GET `http://localhost:8000/jobs/{job_id}`
- Response (example):
```json
{
  "id": "abcdef123456",
  "status": "queued|running|finished|failed",
  "created_at": "2025-12-14T19:00:00Z",
  "started_at": "2025-12-14T19:00:05Z",
  "finished_at": "2025-12-14T19:03:12Z",
  "error": null,
  "has_result": true
}
```

3) Fetch job result:
- GET `http://localhost:8000/jobs/{job_id}/result`
- If job is not finished, the endpoint returns `202 Accepted` with current job status.
- If job finished successfully, the endpoint returns `200 OK` with the analysis summary (same JSON-friendly format as the synchronous `/analyze` response).

Notes and recommendations:
Background workers (RQ + Redis) and secure artifact downloads
- For small experiments the built-in in-process job manager is convenient. For production you can enable an RQ/Redis worker for resilient, off-process job execution.

Quick steps to enable RQ:
  1. Install & run Redis (the service that RQ uses as a broker/storage).
     - Example local URL: `redis://localhost:6379/0`
  2. Install the Python packages:
     ```bash
     pip install rq redis
     ```
  3. Configure environment variables:
     ```bash
     export BIB_USE_RQ=1
     export REDIS_URL=redis://localhost:6379/0
     # Optional: control where job outputs are written
     export BIB_JOB_OUTPUT_DIR=/path/to/analysis_outputs
     ```
  4. Start a worker listening on the queue name used by the app (default: `simple-bib-queue`).
     Run this from the project root (so the worker can import the `jobs` module):
     ```bash
     rq worker simple-bib-queue
     ```
     Or:
     ```bash
     python -m rq worker simple-bib-queue
     ```

How the async flow & downloads work
- Enqueue an async analysis:
  - `POST http://localhost:8000/analyze_async`
  - Body: same JSON as `/analyze` (query, max_results, sources, use_cache, cache_ttl_hours)
  - Response: `{"job_id":"<id>"}`

- Poll job status:
  - `GET http://localhost:8000/jobs/{job_id}`
  - Response includes `status` (`queued|running|finished|failed`) and timestamps.

- When finished, fetch the result:
  - `GET http://localhost:8000/jobs/{job_id}/result`
  - If finished, the response will include `artifact_info` with `artifact_id`, `download_urls` (mapping of export keys to download URLs), and `download_token` (if a token was issued).

- Artifact endpoints (use the `artifact_id` and token from the job result):
  - List files: `GET /artifacts/{artifact_id}/files?token=<token>`
  - Download a file: `GET /artifacts/{artifact_id}/download/{filename}?token=<token>`
  - Example download flow:
    ```bash
    # enqueue
    curl -X POST http://localhost:8000/analyze_async \
      -H 'Content-Type: application/json' \
      -d '{"query":"machine learning"}'
    # poll status and get artifact info, then download:
    curl -L "http://localhost:8000/artifacts/<artifact_id>/download/<filename>?token=<token>" -o my_graph.gexf
    ```

Notes & security recommendations
- The implementation returns download URLs (and a token) so clients don't receive raw filesystem paths. Tokens are simple by-design and stored in memory in the running process for convenience; for production you should:
  - Add authentication (API keys / OAuth / session auth)
  - Use signed URLs or short-lived tokens stored persistently (DB or Redis)
  - Enforce token TTLs, origin/CORS restrictions, and RBAC as needed
  - Consider serving large files via a dedicated file server or signed S3 URLs in production

Synchronous `/analyze` note
- The synchronous `POST /analyze` now also runs the job in a job-friendly wrapper and returns artifact metadata (artifact id + download URLs / token) for immediate downloads if exports are generated.

Flutter prototype
- There's a small Flutter scaffold under `frontend/flutter_app`. Quick start:
  ```bash
  cd frontend/flutter_app
  flutter pub get
  flutter run -d chrome   # run the web prototype
  ```
- The prototype demonstrates posting to `/analyze_async`, polling `/jobs/{job_id}` and using the returned download URLs to fetch artifacts. See `frontend/flutter_app/README.md` for more details and development tips.

### Notebook usage (optional)

You can also use these utilities from a Jupyter notebook. Example:
```python
from bibliometric_crawler import BibliometricCrawler

crawler = BibliometricCrawler()
results = crawler.process_query("machine learning in healthcare")

# Or programmatically use the pipeline
from bibliometrics import analyze_field
res = analyze_field("machine learning in healthcare", max_results_per_source=200, output_dir="analysis_output")
```
Run `jupyter notebook` or `jupyter lab` from the environment where dependencies are installed.

### Programmatic Usage

```python
from bibliometric_crawler import BibliometricCrawler

# Initialize crawler
crawler = BibliometricCrawler()

# Process a query
results = crawler.process_query("machine learning in healthcare")

# Access results
print(f"Total results: {results['total_results']}")
print(f"Results by database: {results['result_summary']}")
print(f"Filtering guidance: {results['filtering_guidance']}")
```

Notes:
- Ensure `GROQ_API_KEY` is present in your `.env` (required for AI-driven query analysis and filtering).
- For authoritative citation metrics, provide `SCOPUS_API_KEY` and/or `WOS_API_KEY` in `.env` when needed.
- If you encounter trouble installing `fa2`, the dashboard still works and uses a reliable spring layout as a fallback.

## Architecture

### Components

1. **bibliometric_crawler.py**: Main orchestrator that coordinates the entire process
   - Query analysis with Groq AI
   - Database crawling coordination
   - Result filtering and normalization

2. **crawlers.py**: Individual crawler implementations for each academic database
   - Base crawler class with common functionality
   - Specific implementations for each database (currently placeholders)

### How It Works

1. **User Query**: User provides a natural language search query
2. **AI Analysis**: Groq AI analyzes the query to:
   - Extract key search terms and variations
   - Determine relevant databases
   - Identify potential synonyms and alternative spellings
3. **Database Crawling**: The system searches selected databases with actual API calls
4. **AI Filtering**: Groq AI processes results to:
   - Identify duplicates (e.g., "data-mining" vs "data mining")
   - Normalize terminology
   - Rank results by relevance
5. **Return Results**: Structured bibliometric data ready for analysis

## API Implementation Status

✅ **Fully Implemented**:
- PubMed (NCBI E-utilities)
- PubChem (NCBI PUG REST)
- Gene (NCBI E-utilities)
- Genome (NCBI E-utilities)
- ERIC (IES API)
- SAGE (via CrossRef API)

✅ **Implemented (Requires API Key)**:
- Web of Science (Clarivate API)
- Scopus (Elsevier API)
- ScienceDirect (Elsevier API)
- IEEE Xplore (IEEE API)
- Springer (Springer Nature API)

⚠️ **Partial Implementation** (Special access required):
- EBSCO (Requires OAuth 2.0 flow)
- Wiley (Requires institutional access)

## API Key Requirements

| Database | API Key Required | Registration Link |
|----------|------------------|-------------------|
| PubMed | Optional* | https://www.ncbi.nlm.nih.gov/account/ |
| ERIC | No | N/A |
| SAGE | No | N/A (uses CrossRef) |
| WoS | Yes | https://developer.clarivate.com/ |
| Scopus | Yes | https://dev.elsevier.com/ |
| ScienceDirect | Yes | https://dev.elsevier.com/ |
| IEEE | Yes | https://developer.ieee.org/ |
| Springer | Yes | https://dev.springernature.com/ |
| EBSCO | Yes | https://connect.ebsco.com/ |
| Wiley | Yes | https://onlinelibrary.wiley.com/ |

### Optional Python package integrations

Several data sources can be queried using community Python packages or official client libraries that do not require API keys for basic access. Where available, the crawler will prefer these package-based clients (if installed) and fall back to the REST APIs otherwise. This reduces or removes the need for API keys for some sources.

Recommended optional packages and mappings:
- PubMed, NCBI Gene, NCBI Genome
  - Recommended package: Biopython (`Bio.Entrez`)
  - Install: `pip install biopython`
  - Notes: `Entrez` is a first-class client for NCBI E-utilities and can be used without an API key (set an email via `NCBI_EMAIL` or `Entrez.email` to comply with NCBI policy). If you have an NCBI API key it can be used for higher rate limits.

- PubChem
  - Recommended package: `pubchempy`
  - Install: `pip install pubchempy`
  - Notes: PubChem is public and does not require an API key; `pubchempy` provides a convenient Python interface. The crawler will prefer `pubchempy` when installed, otherwise it falls back to the PUG REST API.

- CrossRef (used for publisher-level searches such as SAGE)
  - Recommended package: `habanero`
  - Install: `pip install habanero`
  - Notes: CrossRef does not require an API key for the basic search endpoints. The crawler uses `habanero` if available and falls back to the REST endpoint when not.

Important notes:
- These package-based paths are optional and non-destructive. If a package is not installed the crawler falls back to the REST endpoints (where supported).
- Some sources (Web of Science, Scopus, ScienceDirect, IEEE Xplore, Springer, EBSCO, Wiley) still require API keys or institutional access and cannot be made keyless simply by installing a Python package. Installing a package for those sources does not remove the need for credentials.
- To enable the optional behavior, install the packages above or run:
```bash
pip install -r requirements.txt
```
which includes these optional packages.

### Groq model automatic fallback & inspection utility

The crawler now automatically handles the case where the configured Groq model is decommissioned:
- If a Groq completion call returns an error indicating the configured model is decommissioned, the crawler will:
  1. Attempt to list available Groq models via the Groq API,
  2. Select a recommended candidate using a simple heuristic (prefers models with "versatile", chat-capable models, and larger `*b` sizes like `70b`),
  3. Set `GROQ_MODEL` (in-memory for the running process) to the selected model id and retry the call once.
- If the automatic selection fails, the crawler will fall back to a safe non-AI analysis so execution continues.

To inspect and manage Groq models manually, use the provided helper script `inspect_groq_models.py`:
- List available models:
```bash
python inspect_groq_models.py --list
```
- Suggest the best model by heuristics and test it:
```bash
python inspect_groq_models.py --suggest --test
```
- Apply the suggested model to your local `.env` (will back up `.env` first — use `--yes` to confirm):
```bash
python inspect_groq_models.py --suggest --apply --yes
```
This script is intended to help pick a robust Groq model for your workload. You can also set `GROQ_MODEL` directly in your environment:
```bash
export GROQ_MODEL=llama-3.3-70b-versatile
```
(Or set it in your `.env` file.)

Optional: Cerebras provider fallback
- The crawler can optionally use Cerebras Inference as a provider fallback if Groq is unavailable or a suitable Groq model cannot be selected.
- To enable Cerebras fallback:
  1. Install the Cerebras SDK:
  ```bash
  pip install cerebras_cloud_sdk
  ```
  2. Add your Cerebras API key and (optionally) preferred model to your `.env`:
  ```env
  CEREBRAS_API_KEY=your_cerebras_api_key_here
  CEREBRAS_MODEL=llama-3.3-70b
  ```
  3. Behavior: on Groq failure (including model decommission), the crawler will attempt Groq automatic model selection first; if that does not produce a valid response and `CEREBRAS_API_KEY` is set, it will then attempt a chat completion with the configured `CEREBRAS_MODEL`.
- You can test Cerebras by setting `CEREBRAS_API_KEY` and running the same `inspect_groq_models.py --suggest --test` flow; the helper scripts will detect the presence of Cerebras and will attempt the provider fallback when appropriate.
- Note: Cerebras fallback requires a valid API key and network access. Keep API keys private and use `.env` for local configuration (do not commit real keys to version control).

### Testing utilities & full-crawl checks

We've added small helper scripts to verify behavior and exercise real endpoints (useful for CI, manual checks, or debugging). These are lightweight and print concise summaries:

- `integration_test.py`
  - Purpose: quick sanity checks for a few data sources that commonly work without API keys (PubChem, SAGE/CrossRef, PubMed).
  - Example:
```bash
python integration_test.py --max-results 5
```

- `full_crawl_test.py`
  - Purpose: sequentially runs a small search across all crawler implementations and reports counts, sample titles, and errors (shows which sources need valid keys).
  - Example (small run):
```bash
python full_crawl_test.py --query "machine learning" --max-results 5 --sample 3
```
  - Note: This is a polite, low-volume test. Some crawlers will return zero results or require keys.

- `debug_crossref.py`
  - Purpose: debug CrossRef queries and locally filter for SAGE items (useful to tune the SAGE search).
  - Example:
```bash
python debug_crossref.py --query "machine learning" --rows 200 --sample 10
```

How to run the tests locally
1. Install dependencies (including optional packages):
```bash
pip install -r requirements.txt
```
2. Ensure your `.env` contains any API keys you want to test (for sources that require keys).
3. Run the quick integration test:
```bash
python integration_test.py --max-results 5
```
4. Run the full-crawler check:
```bash
python full_crawl_test.py --query "machine learning" --max-results 5 --sample 3
```
5. Inspect Groq models and apply a suggested model if needed:
```bash
python inspect_groq_models.py --suggest --test
# optionally, to apply:
python inspect_groq_models.py --suggest --apply --yes
```

These additions make it easier to run live checks, prefer Python clients where possible (reducing the need for API keys), and automatically handle Groq model deprecation by selecting a suitable alternative and retrying.

By using these recommended packages and utilities, the crawler will work with real data in many cases without additional API keys, and provide clear diagnostic messages for sources that still require credentials.

*Optional but recommended for higher rate limits

## Future Development

- [ ] Add OAuth 2.0 flow for EBSCO
- [ ] Add institutional access support for Wiley
- [ ] Add caching to avoid duplicate API calls
- [ ] Implement Flutter UI for better user experience
- [ ] Add export functionality (CSV, JSON, BibTeX)
- [ ] Add visualization of bibliometric data
- [ ] Implement rate limiting and error handling
- [ ] Add unit tests

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

See LICENSE file for details.

## Support

For issues or questions, please open an issue on GitHub.
