# Simple-bibliometric — v1.0.0 (Just released)

Simple-bibliometric is a compact, production-minded bibliometric crawler and analysis pipeline that ships with improved AI integration, key-validation diagnostics, and fast concurrent crawling.

What’s new in this release
- ✅ Groq AI as primary query analyzer with intelligent fallbacks
- ✅ Integration mode: validate API keys with cached probe results and TTL
- ✅ Parallelized crawling (configurable `max_workers`) for fast real-world performance
- ✅ Tools for diagnostics: `tools/verify_scopes.py` and `tools/perf_benchmark.py`
- ✅ Cleanup and streamlined repository layout

---

A lightweight bibliometric crawler and analysis pipeline with AI-powered query analysis and filtering. Designed for experiments and small deployments; production-ready features include job queues, caching, and configurable data source integrations.

## Key features
- Groq AI for query analysis (primary), with optional fallbacks (Cerebras, Cloudflare)
- Crawls multiple academic sources (PubMed, Scopus, WoS, Springer, etc.)
- Shared API-key fallbacks (NCBI and Elsevier families) to simplify configuration
- Validation mode for API keys with disk caching and TTL
- Concurrent crawling (ThreadPoolExecutor) for better throughput
- CLI, Streamlit dashboard, and FastAPI server interfaces

---

## Quick start

1. Clone and create a venv:
```bash
git clone https://github.com/rqzbeh/Simple-bibliometric.git
cd Simple-bibliometric
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. Copy `.env.example` and set `GROQ_API_KEY` at minimum:
```bash
cp .env.example .env
# edit .env and add your GROQ_API_KEY
```

3. Run a sample interactive query:
```bash
python bibliometric_crawler.py
# or run a one-shot validation check:
python bibliometric_crawler.py --validate-keys
# to invalidate cache and re-check:
python bibliometric_crawler.py --validate-keys --invalidate-cache
```

---

## Configuration & environment variables
- REQUIRED: `GROQ_API_KEY`
- Optional keys (examples): `PUBMED_API_KEY`, `SCOPUS_API_KEY`, `WOS_API_KEY`, `SCIENCEDIRECT_API_KEY`, `SPRINGER_API_KEY`, `IEEE_API_KEY`.

Notes:
- NCBI family (PubMed, PubChem, Gene, Genome) support a shared key: setting `PUBMED_API_KEY` will be used as a fallback for the others.
- Elsevier family (Scopus, ScienceDirect) can share `SCOPUS_API_KEY` / `SCIENCEDIRECT_API_KEY`.
- Some providers do not require keys for public endpoints (e.g., parts of NCBI), and others require institutional or scoped keys.

---

## Validation mode (integration)
- Run `python bibliometric_crawler.py --validate-keys` to perform lightweight probes against each configured source.
- Results are cached to `.cache/validation_cache.json` with a TTL (default 1 hour). Use `--invalidate-cache` to force revalidation.
- Validation runs are parallelized for speed.

Example output:
```
Validating configured API keys (this may perform small probe requests)...
 - pubmed: OK - OK
 - scopus: INVALID (status=401) - {"error-response":{...}}
```

---

## Performance & concurrency
- Crawling and validation probes run with a `ThreadPoolExecutor` (IO-bound parallelism).
- Control parallelism via the `max_workers` argument when constructing `BibliometricCrawler` or `--max-workers` flag in CLI validation mode.

---

## Running tests
```bash
pip install -r requirements.txt
pytest
```

---

## VPS Installation Guide (Ubuntu)
1. Create a server and connect (Ubuntu 22.04+ recommended)
2. Update packages and install system deps:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git build-essential
```
3. Clone & set up project:
```bash
git clone https://github.com/rqzbeh/Simple-bibliometric.git
cd Simple-bibliometric
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
4. Configure environment variables (use a secure file `/etc/simple-bibliometric.env` or systemd unit `EnvironmentFile=`):
```bash
# Example: /etc/simple-bibliometric.env
GROQ_API_KEY=your_groq_key
SCOPUS_API_KEY=your_scopus_key
# restrict permissions
sudo chown root:root /etc/simple-bibliometric.env
sudo chmod 600 /etc/simple-bibliometric.env
```
5. (Optional) Configure systemd service (see `deployment/bibliometric-api.service` and `deployment/bibliometric-worker@.service` for examples). Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now bibliometric-api.service
sudo systemctl enable --now bibliometric-worker@default.service
```
6. Monitor logs with `journalctl -u bibliometric-api -f` or `systemctl status bibliometric-api`.

---

## Repo cleanup proposal
I can remove or archive files that are not needed in the canonical repo. Suggested candidates (please confirm before I delete):
- `debug_crossref.py` (utility/debugging)
- `example.py` (sample usage duplicates other scripts)
- `full_crawl_test.py` (long-running integration test; keep in a tools folder if needed)
- `scripts/run_sample_query.py` (move to examples/ or tools/)

I'll prepare a PR that removes the above files (or moves them to `tools/`) and documents the change in the PR description for review.

---

## Contributing
Contributions welcome. Please open an issue to discuss larger changes and follow the included `CONTRIBUTING.md`.

---

## License
MIT

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

## 🚀 Production Deployment

### Architecture Overview

Simple-bibliometric is designed for both development and production environments:

- **Development**: In-process job queue with ThreadPoolExecutor
- **Production**: RQ (Redis Queue) with persistent job storage

### Deployment Options

#### Option 1: Single Server Deployment

**Requirements:**
- Ubuntu/Debian Linux server
- Python 3.8+
- Redis (optional, for job queue)
- Nginx (for reverse proxy)
- Systemd (for service management)

**Setup Steps:**

1. **Install System Dependencies:**
```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv redis-server nginx
```

2. **Clone and Setup Application:**
```bash
cd /opt
sudo git clone https://github.com/rqzbeh/Simple-bibliometric.git
cd Simple-bibliometric
sudo python3 -m venv venv
sudo venv/bin/pip install -r requirements.txt
```

3. **Configure Environment:**
```bash
sudo cp .env.example .env
sudo nano .env  # Add your API keys
```

4. **Create Systemd Service for API:**
```bash
sudo tee /etc/systemd/system/bibliometric-api.service << EOF
[Unit]
Description=Simple Bibliometric API
After=network.target redis.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/Simple-bibliometric
Environment="PATH=/opt/Simple-bibliometric/venv/bin"
ExecStart=/opt/Simple-bibliometric/venv/bin/uvicorn api:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF
```

5. **Create Systemd Service for RQ Worker:**
```bash
sudo tee /etc/systemd/system/bibliometric-worker.service << EOF
[Unit]
Description=Simple Bibliometric RQ Worker
After=network.target redis.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/Simple-bibliometric
Environment="PATH=/opt/Simple-bibliometric/venv/bin"
Environment="BIB_USE_RQ=1"
Environment="REDIS_URL=redis://localhost:6379/0"
ExecStart=/opt/Simple-bibliometric/venv/bin/rq worker simple-bib-queue
Restart=always

[Install]
WantedBy=multi-user.target
EOF
```

6. **Configure Nginx:**
```bash
sudo tee /etc/nginx/sites-available/bibliometric << EOF
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/bibliometric /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

7. **Start Services:**
```bash
sudo systemctl enable redis-server bibliometric-api bibliometric-worker
sudo systemctl start redis-server bibliometric-api bibliometric-worker
```

8. **Check Status:**
```bash
sudo systemctl status bibliometric-api bibliometric-worker
```

#### Option 2: Docker Deployment

**Create `Dockerfile`:**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc g++ build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Expose ports
EXPOSE 8000 8501

# Run API server
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Create `docker-compose.yml`:**
```yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    restart: always
    volumes:
      - redis-data:/data

  api:
    build: .
    restart: always
    ports:
      - "8000:8000"
    env_file:
      - .env
    environment:
      - BIB_USE_RQ=1
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
    volumes:
      - ./analysis_outputs:/app/analysis_outputs

  worker:
    build: .
    restart: always
    command: rq worker simple-bib-queue
    env_file:
      - .env
    environment:
      - BIB_USE_RQ=1
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
    volumes:
      - ./analysis_outputs:/app/analysis_outputs

  streamlit:
    build: .
    restart: always
    command: streamlit run app.py --server.port=8501 --server.address=0.0.0.0
    ports:
      - "8501:8501"
    env_file:
      - .env
    depends_on:
      - redis

volumes:
  redis-data:
```

**Deploy:**
```bash
docker-compose up -d
```

#### Option 3: Kubernetes Deployment

See `k8s/` directory for Kubernetes manifests (deployment, service, ingress, configmap).

### Performance Tuning

**For High-Volume Production:**

1. **Redis Configuration** (`/etc/redis/redis.conf`):
```conf
maxmemory 2gb
maxmemory-policy allkeys-lru
save 900 1
save 300 10
```

2. **RQ Worker Scaling:**
```bash
# Start multiple workers for parallel processing
for i in {1..4}; do
    rq worker simple-bib-queue --name worker-$i &
done
```

3. **API Server Scaling:**
```bash
# Use multiple workers with Gunicorn
gunicorn api:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

4. **Nginx Rate Limiting:**
```nginx
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

location /api {
    limit_req zone=api_limit burst=20 nodelay;
    proxy_pass http://localhost:8000;
}
```

### Monitoring and Logging

**1. Application Logs:**
```bash
# View API logs
sudo journalctl -u bibliometric-api -f

# View worker logs
sudo journalctl -u bibliometric-worker -f
```

**2. Redis Monitoring:**
```bash
redis-cli INFO stats
redis-cli MONITOR
```

**3. Job Queue Monitoring:**
```python
from rq import Queue
from redis import Redis

redis_conn = Redis.from_url('redis://localhost:6379/0')
q = Queue('simple-bib-queue', connection=redis_conn)

print(f"Queued: {q.count}")
print(f"Failed: {len(q.failed_job_registry)}")
```

### Backup and Recovery

**Backup Redis Data:**
```bash
# Create backup
redis-cli SAVE
cp /var/lib/redis/dump.rdb /backup/redis-$(date +%Y%m%d).rdb

# Restore backup
sudo systemctl stop redis-server
sudo cp /backup/redis-20231201.rdb /var/lib/redis/dump.rdb
sudo systemctl start redis-server
```

**Backup Job Outputs:**
```bash
tar -czf job-outputs-$(date +%Y%m%d).tar.gz /var/lib/bib-jobs/
```

## 🧪 Testing

### Running Tests

The project includes comprehensive test suites:

**1. Unit Tests:**
```bash
# Run all tests
python test_crawlers.py
python test_jobs.py
python test_api_jobs.py
python test_redis_artifacts.py
```

**2. Integration Tests:**
```bash
# Quick sanity check (no API keys needed)
python integration_test.py --max-results 5

# Full crawler test (tests all data sources)
python full_crawl_test.py --query "machine learning" --max-results 5
```

**3. API Tests:**
```bash
# Test API endpoints
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"query":"test","max_results":10}'
```

### Continuous Integration

**GitHub Actions Workflow** (`.github/workflows/test.yml`):
```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python test_crawlers.py
      - run: python test_jobs.py
```

### Test Coverage

Current test coverage:
- ✅ Crawler instantiation and basic operations
- ✅ Job queue (in-process and RQ backends)
- ✅ API endpoints (sync and async)
- ✅ Cache utilities
- ✅ Data export formats
- ✅ Network visualization

## 🔧 Troubleshooting

### Common Issues

#### Issue: "GROQ_API_KEY not found"
**Solution:**
```bash
# Ensure .env file exists and contains GROQ_API_KEY
cp .env.example .env
nano .env  # Add your Groq API key
```

#### Issue: "Module 'streamlit' not found"
**Solution:**
```bash
pip install -r requirements.txt
```

#### Issue: "Failed to resolve hostname" (Network Errors)
**Cause:** Running in an environment without internet access or with DNS issues.
**Solution:**
- Check network connectivity: `ping google.com`
- Verify DNS: `nslookup eutils.ncbi.nlm.nih.gov`
- Configure proxy if needed

#### Issue: "fa2 installation fails"
**Cause:** Missing C compiler for building the ForceAtlas2 extension.
**Solution:**
```bash
# Ubuntu/Debian
sudo apt-get install build-essential python3-dev

# macOS
xcode-select --install

# Or skip fa2 - the app will use spring layout fallback
```

#### Issue: "Rate limit exceeded"
**Cause:** Too many API requests to a data source.
**Solution:**
- Reduce `max_results` parameter
- Add API keys for higher rate limits
- Enable caching with `use_cache=True`
- Wait before retrying

#### Issue: "Redis connection refused"
**Solution:**
```bash
# Start Redis server
sudo systemctl start redis-server

# Or use in-process backend (no Redis needed)
unset BIB_USE_RQ
```

#### Issue: "Job stuck in 'running' state"
**Solution:**
```bash
# Check worker status
rq info --url redis://localhost:6379/0

# Restart worker
sudo systemctl restart bibliometric-worker
```

### Debug Mode

Enable detailed logging:
```bash
export LOG_LEVEL=DEBUG
python bibliometric_crawler.py
```

Or in `.env`:
```env
LOG_LEVEL=DEBUG
```

### Getting Help

1. **Check Documentation:** Review this README and `API_INTEGRATION_GUIDE.md`
2. **Run Diagnostics:**
   ```bash
   python inspect_groq_models.py --list
   python integration_test.py --max-results 3
   ```
3. **Open an Issue:** https://github.com/rqzbeh/Simple-bibliometric/issues
4. **Include Information:**
   - Python version: `python --version`
   - Package versions: `pip freeze`
   - Error messages and stack traces
   - Steps to reproduce

## 🔒 Security Best Practices

### API Key Management

**❌ DON'T:**
- Commit `.env` file to version control
- Hardcode API keys in source code
- Share API keys in logs or error messages
- Use production keys in development

**✅ DO:**
- Use `.env` file for local development
- Use environment variables in production
- Use secrets management (AWS Secrets Manager, HashiCorp Vault)
- Rotate API keys regularly
- Use separate keys for dev/staging/prod

### Network Security

**Enable HTTPS:**
```nginx
server {
    listen 443 ssl http2;
    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
    
    location / {
        proxy_pass http://localhost:8000;
    }
}
```

**Rate Limiting:**
```python
# In api.py, add rate limiting middleware
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/analyze")
@limiter.limit("10/minute")
async def analyze_endpoint(...):
    ...
```

**CORS Configuration:**
```python
# In api.py, restrict CORS origins in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],  # Not ["*"]
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
```

### Data Security

**1. Sanitize User Input:**
- Validate query strings
- Limit input length
- Escape special characters

**2. Secure File Downloads:**
- Use time-limited tokens
- Validate file paths (prevent directory traversal)
- Implement access control

**3. Secure Redis:**
```conf
# /etc/redis/redis.conf
bind 127.0.0.1
requirepass your-strong-redis-password
```

**4. Regular Updates:**
```bash
# Update dependencies regularly
pip install --upgrade -r requirements.txt
pip audit  # Check for vulnerabilities
```

### Compliance

- **GDPR**: If collecting user data, implement privacy controls
- **API Terms**: Respect rate limits and terms of service for each database API
- **Citation**: Properly attribute data sources in outputs

## 🤝 Contributing

We welcome contributions! Here's how you can help:

### Getting Started

1. **Fork the repository**
2. **Create a feature branch:**
   ```bash
   git checkout -b feature/amazing-feature
   ```
3. **Make your changes**
4. **Test thoroughly:**
   ```bash
   python test_crawlers.py
   python test_jobs.py
   ```
5. **Commit with clear messages:**
   ```bash
   git commit -m "Add amazing feature: description"
   ```
6. **Push and create a Pull Request**

### Contribution Guidelines

**Code Style:**
- Follow PEP 8 style guide
- Use type hints where possible
- Add docstrings to functions and classes
- Keep functions focused and small

**Testing:**
- Add tests for new features
- Ensure existing tests pass
- Test edge cases and error conditions

**Documentation:**
- Update README for user-facing changes
- Add inline comments for complex logic
- Update API_INTEGRATION_GUIDE.md for new data sources

**Adding a New Data Source:**

1. Create a new crawler class in `crawlers.py`:
```python
class MyNewCrawler(BaseCrawler):
    def __init__(self, api_key: str = None):
        super().__init__("MyNewSource", api_key)
        self.base_url = "https://api.mynewsource.com"
    
    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        # Implement search logic
        pass
```

2. Register in `bibliometric_crawler.py`:
```python
from crawlers import MyNewCrawler

self.crawlers = {
    # ... existing crawlers ...
    "mynewsource": MyNewCrawler(os.getenv("MYNEWSOURCE_API_KEY")),
}
```

3. Add tests in `test_crawlers.py`
4. Update documentation

### Areas for Contribution

- 🐛 Bug fixes
- ✨ New data source integrations
- 📚 Documentation improvements
- 🧪 Additional tests
- ⚡ Performance optimizations
- 🎨 UI/UX enhancements
- 🌍 Internationalization
- 📊 New visualization types

## 📊 Project Status

### Completed Features

✅ Multi-database crawler with 13 data sources  
✅ AI-powered query analysis and filtering  
✅ Author metrics computation (h-index, g-index)  
✅ Network visualization with multiple layouts  
✅ Time series analysis and forecasting  
✅ Multiple export formats (CSV, JSON, BibTeX, GEXF)  
✅ RESTful API with async job queue  
✅ Streamlit dashboard  
✅ Smart caching system  
✅ Comprehensive test suite  
✅ Production deployment guides  
✅ Docker support  
✅ Groq model auto-selection and Cerebras fallback  
✅ Flutter mobile UI prototype  

### Known Limitations

- EBSCO requires OAuth 2.0 flow (partial implementation)
- Wiley requires institutional access
- Some data sources have rate limits
- Citation counts vary by data source quality
- Network analysis performance degrades with very large graphs (>10k nodes)

### Roadmap

**Short Term:**
- [ ] Complete EBSCO OAuth 2.0 integration
- [ ] Add institutional proxy support for Wiley
- [ ] Implement GraphQL API
- [ ] Add WebSocket support for real-time progress
- [ ] Enhance Flutter UI with full feature parity

**Long Term:**
- [ ] Machine learning for research trend prediction
- [ ] Collaborative filtering recommendations
- [ ] Multi-user support with authentication
- [ ] Cloud deployment templates (AWS, GCP, Azure)
- [ ] Integration with reference managers (Zotero, Mendeley)

## Future Development

### Completed Previously Planned Features

✅ Caching to avoid duplicate API calls  
✅ Flutter UI for better user experience  
✅ Export functionality (CSV, JSON, BibTeX)  
✅ Visualization of bibliometric data  
✅ Rate limiting and error handling  
✅ Unit tests  

### New Development Goals

- [ ] GraphQL API for flexible queries
- [ ] Machine learning-based result ranking
- [ ] Multi-language support (i18n)
- [ ] Advanced analytics dashboard with D3.js
- [ ] Plugin system for custom data sources
- [ ] Blockchain-based citation tracking

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

See LICENSE file for details.

## Support

For issues or questions, please open an issue on GitHub.
