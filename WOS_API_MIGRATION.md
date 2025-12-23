# Web of Science API Migration: WoS Starter API

## What Changed

The WoS crawler has been updated to use the **modern WoS Starter API v1** endpoint instead of the older (and less reliable) WoS API Expanded endpoint.

### Before
```
https://api.clarivate.com/api/wos  (Older endpoint)
```

### After
```
https://api.clarivate.com/apis/wos-starter/v1  (Modern, free, recommended)
```

## Key Improvements

| Aspect | Old API | WoS Starter API |
|--------|---------|-----------------|
| **Endpoint** | `/api/wos` | `/apis/wos-starter/v1` |
| **Response Format** | Complex XML with nested structures | Simple, clean JSON |
| **Free Tier** | Limited | 50 requests/day (Free Trial) |
| **Auth Header** | `X-ApiKey` or `X-APIKey` (both supported) | **`X-ApiKey` only** |
| **Query Format** | Complex parameters (databaseId, usrQuery, count, firstRecord) | Simple query language (`q`, `db`, `limit`, `page`) |
| **Field Parsing** | Deep XML nesting, complex navigation | Simple JSON path access |
| **Times Cited** | Available | Available (Institutional plan required) |

## New Query Language

WoS Starter API uses **Web of Science Query Language (WoS QL)** with field tags:

### Supported Field Tags
- `TI` - Title search
- `AU` - Author search
- `DO` - DOI search
- `PY` - Publication Year
- `TS` - Topic (title, abstract, keywords - default)
- `SO` - Source title (journal name)
- `IS` - ISSN/ISBN
- `DT` - Document Type
- `PMID` - PubMed ID

### Example Queries
```python
# Old format (no longer used)
"cancer genomics"

# New format (auto-converted to TS search)
"cancer genomics"  → "TS=(cancer genomics)"

# With explicit field tags
"TI=(machine learning)"        # Title contains "machine learning"
"AU=(Smith J)"                 # Author "Smith J"
"PY=2020"                      # Published in 2020
"PY=(2018-2021) AND TI=(cancer)"  # Complex query
```

## Code Changes

### Updated Response Parsing
The old deeply nested XML structure:
```python
response.get("Data", {}).get("Records", {}).get("records", {}).get("REC", [])
```

Is now simplified to clean JSON:
```python
response.get("hits", [])  # Direct access to results
```

### Updated Parameters
**Old:**
```python
params = {
    "databaseId": "WOS",
    "usrQuery": query,
    "count": 100,
    "firstRecord": 1,
}
```

**New:**
```python
params = {
    "q": query,           # Query string
    "db": "WOS",          # Database (WOS, BIOABS, MEDLINE, etc.)
    "limit": 50,          # Max 50 per page
    "page": 1,
    "sort_field": "TC+D"  # Sort by Times Cited descending
}
```

## Authentication

### API Key Requirements
- **Header:** `X-ApiKey` (required)
- **Format:** Plain API key value (no "Bearer" prefix, no special formatting)

```bash
curl -X GET "https://api.clarivate.com/apis/wos-starter/v1/documents?q=TI=(cancer)&limit=10" \
  -H "X-ApiKey: YOUR_API_KEY_HERE"
```

### Plans & Rate Limits
- **Free Trial**: 50 requests/day, basic metadata (no times cited)
- **Free Institutional Member**: 5 requests/second, 5,000 requests/day (with times cited)
- **Free Institutional Integration**: 5 requests/second, 20,000 requests/day

## Response Structure Changes

### Old Response (Complex Nested XML-like JSON)
```json
{
  "Data": {
    "Records": {
      "records": {
        "REC": [
          {
            "static_data": {
              "summary": {
                "titles": {
                  "title": [
                    { "content": "Research Paper Title" }
                  ]
                }
              }
            }
          }
        ]
      }
    }
  }
}
```

### New Response (Clean JSON)
```json
{
  "hits": [
    {
      "title": "Research Paper Title",
      "authors": [
        {"full_name": "Smith, John"},
        {"full_name": "Jones, Mary"}
      ],
      "year": 2020,
      "identifiers": {
        "doi": "10.1234/example"
      },
      "citations": {
        "tc_list": {
          "silo_tc": {
            "local_count": 42
          }
        }
      }
    }
  ]
}
```

## Migration Checklist

- ✅ Updated endpoint to `/apis/wos-starter/v1`
- ✅ Changed query parameter from `usrQuery` to `q`
- ✅ Added WoS Query Language support (field tags like TI=, AU=, PY=)
- ✅ Updated response parsing for clean JSON format
- ✅ Removed support for old nested XML structure
- ✅ Updated rate limit allowance (5 req/sec vs 1 req/sec)
- ✅ Updated error handling for new response format
- ✅ All tests passing

## Troubleshooting

### Getting 401 Unauthorized?
Your API key is invalid or not activated for the WoS Starter API. Check:
1. [Clarivate Developer Portal](https://developer.clarivate.com/) - verify key is active
2. Ensure key is registered for "WoS Starter API"
3. Try the Free Trial plan if you don't have API access

### Getting 400 Bad Request?
Check your query syntax:
- Ensure you're using valid field tags (TI=, AU=, PY=, etc.)
- Wrap values in parentheses: `TI=(your search)`
- Use AND/OR for complex queries: `TI=(cancer) AND PY=(2020-2021)`

### No results returned?
- Try a simpler query: `cancer` instead of complex syntax
- Check that your field tag is correct
- Verify the search terms exist in WoS database

## References

- **Official Documentation**: https://developer.clarivate.com/apis/wos-starter
- **Query Language Guide**: [WoS Query Language Docs](https://webofscience.help.clarivate.com/en-us/Content/home.htm)
- **Code Examples**: https://github.com/clarivate/wos_api_usecases
- **Python Client**: https://github.com/clarivate/wosstarter_python_client
