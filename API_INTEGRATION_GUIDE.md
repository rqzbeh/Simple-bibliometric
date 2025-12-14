# API Integration Guide

This document provides guidance for implementing the actual API integrations for each academic database.

## General Structure

Each crawler in `crawlers.py` follows this pattern:

```python
class DatabaseCrawler(BaseCrawler):
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.base_url = "https://api.database.com/"
    
    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        # Implement actual API call here
        params = {
            'q': query,
            'limit': max_results
        }
        response = self._make_request('/search', params)
        return self._process_response(response)
    
    def _process_response(self, response: Dict) -> List[Dict[str, Any]]:
        # Convert API response to standardized format
        results = []
        for item in response.get('items', []):
            results.append({
                'title': item.get('title'),
                'authors': item.get('authors'),
                'year': item.get('year'),
                'doi': item.get('doi'),
                'abstract': item.get('abstract'),
                'source': self.__class__.__name__,
                'citations': item.get('citation_count'),
                'url': item.get('url')
            })
        return results
```

## Standardized Output Format

All crawlers should return results in this format:

```python
{
    'title': str,          # Publication title
    'authors': List[str],  # List of author names
    'year': int,           # Publication year
    'doi': str,            # Digital Object Identifier
    'abstract': str,       # Abstract text
    'source': str,         # Database name
    'citations': int,      # Citation count
    'url': str,            # Link to publication
    'keywords': List[str], # Optional: Keywords
    'journal': str,        # Optional: Journal name
    'volume': str,         # Optional: Volume
    'issue': str,          # Optional: Issue
    'pages': str           # Optional: Page range
}
```

## Database-Specific Implementation Notes

### 1. Web of Science (WoS)
- **API Documentation**: https://developer.clarivate.com/apis/wos
- **Authentication**: API Key in header
- **Rate Limit**: Varies by subscription
- **Key Endpoints**:
  - `/search` - Search publications
  - `/records` - Get detailed records

### 2. Scopus
- **API Documentation**: https://dev.elsevier.com/sc_apis.html
- **Authentication**: API Key (X-ELS-APIKey header)
- **Rate Limit**: 20,000 requests per week (varies)
- **Key Endpoints**:
  - `/content/search/scopus` - Search
  - `/content/abstract/scopus_id/` - Get details

### 3. ScienceDirect
- **API Documentation**: https://dev.elsevier.com/sd_apis.html
- **Authentication**: API Key (X-ELS-APIKey header)
- **Rate Limit**: Similar to Scopus
- **Key Endpoints**:
  - `/content/search/sciencedirect` - Search
  - `/content/article/` - Get full text

### 4. PubMed
- **API Documentation**: https://www.ncbi.nlm.nih.gov/books/NBK25501/
- **Authentication**: API Key (optional, increases rate limit)
- **Rate Limit**: 3 req/sec without key, 10 req/sec with key
- **Key Endpoints**:
  - `esearch.fcgi` - Search
  - `efetch.fcgi` - Fetch details
  - `esummary.fcgi` - Get summaries

Example:
```python
def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
    # Search for IDs
    search_params = {
        'db': 'pubmed',
        'term': query,
        'retmax': max_results,
        'retmode': 'json'
    }
    search_result = self._make_request('esearch.fcgi', search_params)
    ids = search_result.get('esearchresult', {}).get('idlist', [])
    
    # Fetch details
    fetch_params = {
        'db': 'pubmed',
        'id': ','.join(ids),
        'retmode': 'xml'
    }
    details = self._make_request('efetch.fcgi', fetch_params)
    return self._process_pubmed_xml(details)
```

### 5. PubChem
- **API Documentation**: https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest
- **Authentication**: None required
- **Rate Limit**: No more than 5 requests per second
- **Key Endpoints**:
  - `/pug/compound/name/{name}/JSON`
  - `/pug/compound/cid/{cid}/property/{properties}/JSON`

### 6. NCBI Gene
- **API Documentation**: https://www.ncbi.nlm.nih.gov/books/NBK25501/
- **Authentication**: Same as PubMed
- **Database**: `gene`
- **Similar to PubMed but use db=gene**

### 7. NCBI Genome
- **API Documentation**: https://www.ncbi.nlm.nih.gov/books/NBK25501/
- **Authentication**: Same as PubMed
- **Database**: `genome`

### 8. SAGE Journals
- **API Documentation**: Contact SAGE for API access
- **Authentication**: API Key
- **Note**: May require institutional access

### 9. IEEE Xplore
- **API Documentation**: https://developer.ieee.org/
- **Authentication**: API Key
- **Rate Limit**: Varies by subscription
- **Key Endpoints**:
  - `/search/articles` - Search articles

Example:
```python
def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
    params = {
        'querytext': query,
        'max_records': max_results,
        'apikey': self.api_key
    }
    response = self._make_request('search/articles', params)
    return self._process_ieee_response(response)
```

### 10. Emerald Insight
- **API Documentation**: https://developers.emeraldinsight.com/
- **Authentication**: API Key
- **Rate Limit**: Varies

### 11. ERIC
- **API Documentation**: https://eric.ed.gov/?api
- **Authentication**: Not required for basic access
- **Key Endpoints**:
  - `/search` - Search education resources

Example:
```python
def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
    params = {
        'search': query,
        'rows': max_results,
        'format': 'json'
    }
    response = self._make_request('search', params)
    return self._process_eric_response(response)
```

### 12. Springer
- **API Documentation**: https://dev.springernature.com/
- **Authentication**: API Key
- **Rate Limit**: 5000 calls/day (basic)
- **Key Endpoints**:
  - `/metadata/json` - Search metadata
  - `/openaccess/json` - Open access content

### 13. EBSCO
- **API Documentation**: https://connect.ebsco.com/s/article/EDS-API-Documentation
- **Authentication**: OAuth 2.0
- **Note**: Requires authentication flow

### 14. Wiley
- **API Documentation**: Contact Wiley for API access
- **Authentication**: API Key
- **Note**: May require institutional subscription

## Error Handling

Always implement proper error handling:

```python
def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
    try:
        response = self._make_request('/search', {'q': query})
        
        if not response:
            print(f"[{self.__class__.__name__}] Empty response")
            return []
        
        if 'error' in response:
            print(f"[{self.__class__.__name__}] API Error: {response['error']}")
            return []
        
        return self._process_response(response)
        
    except requests.exceptions.RequestException as e:
        print(f"[{self.__class__.__name__}] Network error: {e}")
        return []
    except Exception as e:
        print(f"[{self.__class__.__name__}] Unexpected error: {e}")
        return []
```

## Rate Limiting

Implement rate limiting to respect API quotas:

```python
import time
from datetime import datetime, timedelta

class RateLimitedCrawler(BaseCrawler):
    def __init__(self, api_key: Optional[str] = None, requests_per_second: float = 1.0):
        super().__init__(api_key)
        self.requests_per_second = requests_per_second
        self.last_request_time = None
    
    def _rate_limit(self):
        if self.last_request_time:
            elapsed = (datetime.now() - self.last_request_time).total_seconds()
            sleep_time = (1.0 / self.requests_per_second) - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
        self.last_request_time = datetime.now()
    
    def _make_request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self._rate_limit()
        return super()._make_request(endpoint, params)
```

## Testing Individual Crawlers

Test each crawler individually before integration:

```python
if __name__ == "__main__":
    crawler = PubMedCrawler(api_key=os.getenv("PUBMED_API_KEY"))
    results = crawler.search("machine learning", max_results=10)
    
    print(f"Found {len(results)} results")
    for result in results[:3]:
        print(f"- {result['title']} ({result['year']})")
```

## Next Steps

1. Choose a database to implement first (PubMed or ERIC are good starting points as they don't require paid API access)
2. Register for API access and obtain credentials
3. Implement the `search()` method following the patterns above
4. Test with sample queries
5. Iterate for other databases

## Resources

- [Python Requests Documentation](https://requests.readthedocs.io/)
- [Rate Limiting with Python](https://pypi.org/project/ratelimit/)
- [Handling API Errors](https://realpython.com/python-requests/#error-handling)
