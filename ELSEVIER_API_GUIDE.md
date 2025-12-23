# Elsevier API (Scopus/ScienceDirect) Implementation Guide

## Official Documentation Review

Based on official Elsevier technical documentation, here's what the correct implementation should be:

### Authentication Methods

#### 1. **API Key Authentication (Most Common)**
Submit your API key in one of two ways:

**Method A: URL Parameter**
```
https://api.elsevier.com/content/search/scopus?query=heart&apiKey=[apikey]
```

**Method B: HTTP Header (Recommended)**
```
Header: X-ELS-APIKey: [your_api_key]
```

⚠️ **CRITICAL**: The header is **`X-ELS-APIKey`** (note the capitalization: `-APIKey` not `-ApiKey`)

#### 2. **Institutional Token (Insttoken)**
For institutions that have been set up with special tokens:

```
Header: X-ELS-Insttoken: [institutional_token]
```

This is **server-side only** and must come over HTTPS.

#### 3. **Authentication Token (Authtoken)**
For resolving IP conflicts when multiple accounts are associated with the same IP:

**Step 1: Request authentication**
```
GET http://api.elsevier.com/authenticate?platform=SCOPUS
Header: X-ELS-APIKey: [your_api_key]
Header: Accept: text/xml, application/atom+xml (optional, defaults to JSON)
```

**Step 2: Parse response** (XML format shown):
```xml
<authenticate-response>
    <pathChoices>
        <choice id="13177831" name="My Account number one"/>
        <choice id="13177834" name="My Account number two"/>
    </pathChoices>
</authenticate-response>
```

**Step 3: Request specific account** (if multiple choices)
```
GET http://api.elsevier.com/authenticate?platform=SCOPUS&choice=[choiceID]
Header: X-ELS-APIKey: [your_api_key]
```

**Step 4: Extract authtoken from response**
```xml
<authenticate-response choice="[choiceID]" type="ONLINE_REGISTERED">
    <authtoken>
        [LONG_TOKEN_STRING]
    </authtoken>
</authenticate-response>
```

**Step 5: Use authtoken in subsequent requests**
```
Header: X-ELS-APIKey: [your_api_key]
Header: X-ELS-AuthToken: [authtoken_from_step4]
```

⚠️ **Note**: Authtoken expires **2 hours** after issuance.

### API Endpoints

#### Scopus Search
```
https://api.elsevier.com/content/search/scopus?query=[query]&apiKey=[key]
```

**Query Parameters:**
- `query` (required): Your search string
- `count` (optional): Results per page (1-25, default 25)
- `start` (optional): Starting record (0-indexed, default 0)
- `view` (optional): Response detail level (STANDARD, COMPLETE)
- `sort` (optional): Sort field
- `apiKey` (optional): API key (if not using header)

**Headers:**
- `X-ELS-APIKey`: Your API key (required if not in URL)
- `Accept`: `application/json` or `application/xml` (default: JSON)
- `User-Agent`: Your application identifier

#### ScienceDirect Search
```
https://api.elsevier.com/content/search/sciencedirect?query=[query]&apiKey=[key]
```

Same parameters as Scopus.

#### ScienceDirect Article Metadata
```
https://api.elsevier.com/content/metadata/article?query=aff(institution)&apiKey=[key]
```

**Supported Query Fields:**
- `aff` - Affiliation search
- `pub-date` - Publication date (YYYYMMDD format or year)
- `view` - Set to `COMPLETE` to get abstracts
- `httpAccept` - Response format (alternative to Accept header)

**Date Operators:**
- `AFT` - After (before date)
- `BEF` - Before (before date)
- `is` - Exact match

**Example Queries:**
```
aff(university)
aff(broad institute) and pub-date is 2014
aff(harvard) and pub-date AFT 20140630 AND pub-date BEF 20141001
```

### Response Format

**Default: JSON**
```json
{
  "search-results": {
    "@count": 123,
    "@start": 0,
    "@totalResults": "456",
    "entry": [
      {
        "dc:title": "Article Title",
        "dc:creator": "Author Name",
        "dc:identifier": "SCOPUS_ID:12345678",
        "prism:doi": "10.1234/example",
        "prism:coverDate": "2020-01-15",
        "prism:publicationName": "Journal Name",
        "citedby-count": "42"
      }
    ]
  }
}
```

**Alternative: XML** (set `Accept: application/xml`)
```xml
<search-results>
    <dc:title>Article Title</dc:title>
    <dc:creator>Author Name</dc:creator>
    ...
</search-results>
```

### Current Code Issues

Based on the official documentation review, here are issues found in the current implementation:

1. ✅ **Header names**: The code uses both `X-ELS-APIKey` and `X-ELS-ApiKey`
   - Should only be: `X-ELS-APIKey` (uppercase API)
   - Current code has the redundant variant

2. ✅ **Authtoken implementation**: Correctly implemented
   - Calls `/authenticate` endpoint with platform parameter
   - Extracts token from XML response
   - Caches token for 2 hours
   - **Issue**: Platform parameter should match the API being called (SCOPUS vs SCIENCEDIRECT)

3. ✅ **Insttoken implementation**: Correctly implemented
   - Reads from environment variable `ELS_INSTTOKEN`
   - Sends as header `X-ELS-Insttoken`

4. ⚠️ **Response parsing**: Currently expects specific JSON field names
   - Should validate field names against actual API responses
   - May need to handle both JSON and XML responses

5. ⚠️ **Accept header**: Should specify `application/json` or `application/xml` to ensure correct response format

### Recommended Changes

1. **Clean up header variants**:
   - Remove `X-ELS-ApiKey` (non-standard)
   - Keep only `X-ELS-APIKey` (official)
   - Add explicit Accept header for JSON

2. **Verify platform parameters**:
   - ScopusCrawler: `platform=SCOPUS` ✅
   - ScienceDirectCrawler: `platform=SCIENCEDIRECT` ✅

3. **Add better error handling**:
   - Check for `choice` requirement in authtoken response
   - Handle multiple accounts gracefully
   - Log specific error codes from API responses

4. **Test with actual API**:
   - Verify response structure matches expectations
   - Check pagination handling (start/count parameters)
   - Confirm view parameter works as expected

### API Rate Limits

- **Per-second requests**: Depends on your plan
- **Daily limit**: Varies by subscription level
- **Authtoken lifetime**: 2 hours
- **Cache authtoken**: To avoid repeated authentication calls

### Error Responses

**401 Unauthorized** - Likely causes:
1. Invalid API key
2. API key not activated for the service
3. Expired authtoken (refresh with new authentication)
4. Wrong IP address (use authtoken instead)
5. Key not enabled for Authentication API access

**400 Bad Request** - Likely causes:
1. Invalid query syntax
2. Unsupported parameter
3. Missing required parameter

**429 Too Many Requests** - Rate limit exceeded
1. Implement exponential backoff
2. Check your subscription plan limits
3. Use caching to reduce requests

## References

- [API Authentication](https://dev.elsevier.com/tecdoc_api_authentication.html)
- [Search Requests](https://dev.elsevier.com/tecdoc_search_request.html)
- [ScienceDirect IR Integration](https://dev.elsevier.com/tecdoc_sd_ir_integration.html)
- [IR/CRIS/VIVO Guide](https://dev.elsevier.com/tecdoc_ir_cris_vivo.html)
- [Journal Metrics](https://dev.elsevier.com/tecdoc_journal_metrics.html)
- [Text Mining](https://dev.elsevier.com/tecdoc_text_mining.html)
