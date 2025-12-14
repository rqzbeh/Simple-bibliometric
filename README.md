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
