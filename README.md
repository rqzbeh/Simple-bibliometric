# Simple-bibliometric

A bibliometric data crawler powered by Groq AI that searches across multiple academic databases and intelligently filters and normalizes results.

## Features

- **AI-Powered Query Analysis**: Uses Groq AI to understand user queries and determine optimal search strategies
- **Multi-Database Support**: Crawls data from 14 academic sources:
  - Web of Science (WoS)
  - Scopus
  - ScienceDirect
  - PubMed
  - PubChem
  - NCBI Gene
  - NCBI Genome
  - SAGE Journals
  - IEEE Xplore
  - Emerald Insight
  - ERIC
  - Springer
  - EBSCO
  - Wiley Online Library

- **Intelligent Data Filtering**: AI automatically identifies and combines similar results (e.g., "data mining" and "data-mining")
- **Result Normalization**: Deduplicates entries across databases
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
3. **Database Crawling**: The system searches selected databases with optimized queries
4. **AI Filtering**: Groq AI processes results to:
   - Identify duplicates (e.g., "data-mining" vs "data mining")
   - Normalize terminology
   - Rank results by relevance
5. **Return Results**: Structured bibliometric data ready for analysis

## Adding API Integrations

The current implementation includes placeholders for all database APIs. To add actual API integration:

1. Open `crawlers.py`
2. Find the relevant crawler class (e.g., `PubMedCrawler`)
3. Implement the `search()` method with actual API calls
4. Return results in a standardized format

Example:
```python
def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
    params = {
        'term': query,
        'retmax': max_results,
        'retmode': 'json'
    }
    response = self._make_request('esearch.fcgi', params)
    # Process response and return standardized results
    return processed_results
```

## Future Development

- [ ] Implement actual API integrations for each database
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
