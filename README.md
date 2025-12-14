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
