# Contributing to Simple-bibliometric

Thank you for your interest in contributing to Simple-bibliometric! This document provides guidelines and instructions for contributing to the project.

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [How to Contribute](#how-to-contribute)
- [Development Setup](#development-setup)
- [Coding Standards](#coding-standards)
- [Testing Guidelines](#testing-guidelines)
- [Pull Request Process](#pull-request-process)
- [Adding a New Data Source](#adding-a-new-data-source)
- [Documentation](#documentation)
- [Community](#community)

## Code of Conduct

By participating in this project, you agree to maintain a respectful and inclusive environment for all contributors.

### Our Standards

- Use welcoming and inclusive language
- Be respectful of differing viewpoints and experiences
- Gracefully accept constructive criticism
- Focus on what is best for the community
- Show empathy towards other community members

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/Simple-bibliometric.git
   cd Simple-bibliometric
   ```
3. **Add the upstream repository**:
   ```bash
   git remote add upstream https://github.com/rqzbeh/Simple-bibliometric.git
   ```

## How to Contribute

### Types of Contributions

We welcome several types of contributions:

- 🐛 **Bug Reports**: Found a bug? Let us know!
- ✨ **Feature Requests**: Have an idea? Share it!
- 🔧 **Bug Fixes**: Fix bugs and submit PRs
- 📚 **Documentation**: Improve docs, add examples
- 🎨 **Code Improvements**: Refactoring, optimization
- 🧪 **Tests**: Add or improve test coverage
- 🌍 **Translations**: Help translate the project
- 📊 **New Data Sources**: Add support for new academic databases

### Reporting Bugs

Before creating a bug report:
1. Check existing issues to avoid duplicates
2. Use the latest version of the code
3. Collect information about your environment

**Good bug reports include:**
- Clear, descriptive title
- Steps to reproduce the issue
- Expected vs. actual behavior
- Environment details (OS, Python version, etc.)
- Error messages and stack traces
- Screenshots if applicable

**Example:**
```markdown
**Title:** PubMed crawler fails with SSL error on Python 3.12

**Description:** When running the PubMed crawler on Python 3.12, 
an SSL certificate verification error occurs.

**Steps to Reproduce:**
1. Install on Python 3.12
2. Run `python bibliometric_crawler.py`
3. Enter query: "cancer research"

**Expected:** Results from PubMed
**Actual:** SSLError exception

**Environment:**
- OS: Ubuntu 22.04
- Python: 3.12.0
- Dependencies: (output of `pip freeze`)

**Error Message:**
```
SSLError: [SSL: CERTIFICATE_VERIFY_FAILED]...
```
```

### Suggesting Features

Feature requests should include:
- Clear description of the feature
- Use case / motivation
- Expected behavior
- Alternative solutions considered
- Mockups or examples (if applicable)

## Development Setup

### 1. Set Up Environment

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install development dependencies
pip install pytest flake8 black mypy pytest-cov
```

### 2. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Add your API keys for testing
nano .env
```

### 3. Run Tests

```bash
# Run all tests
python test_crawlers.py
python test_jobs.py
python test_api_jobs.py

# Run integration tests (requires API keys)
python integration_test.py --max-results 5
```

### 4. Start Development Server

```bash
# Start API server
uvicorn api:app --reload

# Or start Streamlit dashboard
streamlit run app.py
```

## Coding Standards

### Python Style Guide

We follow [PEP 8](https://pep8.org/) with some modifications:

- **Line length**: 88 characters (Black default)
- **Indentation**: 4 spaces
- **Quotes**: Double quotes for strings
- **Imports**: Grouped and sorted (standard lib, third-party, local)

### Code Formatting

We use [Black](https://black.readthedocs.io/) for automatic code formatting:

```bash
# Format all Python files
black .

# Check without modifying
black --check .
```

### Linting

Run linters before submitting:

```bash
# Flake8 for style and errors
flake8 . --max-line-length=88 --extend-ignore=E203

# MyPy for type checking
mypy --ignore-missing-imports .
```

### Code Structure

**Function Guidelines:**
- Keep functions small and focused (< 50 lines ideal)
- Use descriptive names: `fetch_publications()` not `fp()`
- Add type hints for function signatures
- Include docstrings for public APIs

**Example:**
```python
def fetch_publications(
    query: str, 
    max_results: int = 100,
    sources: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Fetch publications from specified data sources.
    
    Args:
        query: Search query string
        max_results: Maximum number of results per source
        sources: List of data source names (None = all sources)
    
    Returns:
        List of publication dictionaries
    
    Raises:
        ValueError: If query is empty
        APIError: If API request fails
    """
    # Implementation
    pass
```

### Documentation Strings

Use Google-style docstrings:

```python
def process_results(results: List[Dict], threshold: float = 0.8) -> List[Dict]:
    """
    Process and filter search results based on relevance threshold.
    
    This function applies AI-powered filtering to remove duplicates
    and low-quality results from the raw search data.
    
    Args:
        results: List of raw result dictionaries from crawlers
        threshold: Minimum relevance score (0.0 to 1.0)
    
    Returns:
        Filtered and deduplicated list of results
    
    Example:
        >>> raw = [{"title": "Paper 1", "score": 0.9}, ...]
        >>> filtered = process_results(raw, threshold=0.85)
        >>> len(filtered) < len(raw)
        True
    """
    pass
```

### Error Handling

**DO:**
```python
try:
    result = api_call()
except requests.RequestException as e:
    logger.error(f"API call failed: {e}")
    return []
```

**DON'T:**
```python
try:
    result = api_call()
except:  # Too broad!
    pass  # Silent failure!
```

### Logging

Use the logging module, not print statements:

```python
import logging

logger = logging.getLogger(__name__)

# Log levels
logger.debug("Detailed debugging information")
logger.info("General information")
logger.warning("Warning message")
logger.error("Error occurred")
logger.critical("Critical error")
```

## Testing Guidelines

### Test Structure

Tests should be organized by component:
- `test_crawlers.py` - Crawler tests
- `test_jobs.py` - Job queue tests
- `test_api_jobs.py` - API endpoint tests
- `test_*.py` - Additional test files

### Writing Tests

**Good test example:**
```python
def test_pubmed_crawler_basic_search():
    """Test that PubMed crawler returns results for valid query."""
    crawler = PubMedCrawler()
    results = crawler.search("cancer", max_results=10)
    
    assert isinstance(results, list)
    assert len(results) <= 10
    
    if results:
        assert "title" in results[0]
        assert "authors" in results[0]
        assert "year" in results[0]
```

### Test Coverage

Aim for:
- **Unit tests**: Individual functions and classes
- **Integration tests**: Component interactions
- **End-to-end tests**: Full workflows

### Running Tests

```bash
# Run all tests
python test_crawlers.py
python test_jobs.py

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test
pytest test_crawlers.py::test_pubmed_crawler_basic_search
```

## Pull Request Process

### 1. Create a Branch

```bash
# Update your fork
git checkout main
git pull upstream main

# Create feature branch
git checkout -b feature/your-feature-name
```

### 2. Make Changes

- Write code following our standards
- Add tests for new functionality
- Update documentation as needed
- Commit with clear messages

### 3. Commit Messages

Follow the [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

**Examples:**
```
feat(crawler): add arXiv data source support

Implement ArxivCrawler class with search and pagination.
Includes rate limiting and error handling.

Closes #123

---

fix(api): handle timeout errors gracefully

Add try-catch block for timeout exceptions in API endpoints.
Return appropriate error message instead of 500 error.

---

docs(readme): update installation instructions

Add Docker installation steps and troubleshooting section.
```

### 4. Push and Create PR

```bash
# Push to your fork
git push origin feature/your-feature-name

# Create PR on GitHub
# Include:
# - Clear description of changes
# - Link to related issues
# - Screenshots (if UI changes)
# - Test results
```

### 5. PR Review Process

- Maintainers will review your PR
- Address feedback and update PR
- Once approved, your PR will be merged

**PR Checklist:**
- [ ] Code follows style guidelines
- [ ] Tests added and passing
- [ ] Documentation updated
- [ ] Commit messages are clear
- [ ] No merge conflicts
- [ ] All CI checks pass

## Adding a New Data Source

Want to add support for a new academic database? Great! Here's how:

### 1. Research the API

- Find official API documentation
- Check rate limits and authentication
- Test API endpoints manually
- Note required parameters and response format

### 2. Create Crawler Class

Create a new class in `crawlers.py`:

```python
class YourNewCrawler(BaseCrawler):
    """
    Crawler for YourNew Database.
    
    API Documentation: https://api.yournew.com/docs
    Rate Limit: 100 requests/hour
    Authentication: API Key
    """
    
    def __init__(self, api_key: str = None):
        super().__init__("YourNew", api_key)
        self.base_url = "https://api.yournew.com/v1"
        self.rate_limit = 100  # requests per hour
    
    def search(
        self, 
        query: str, 
        max_results: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Search YourNew database for publications.
        
        Args:
            query: Search query string
            max_results: Maximum number of results to return
        
        Returns:
            List of publication dictionaries in standard format
        """
        print(f"[YourNew] Searching for: {query}")
        
        # Check API key
        if not self.api_key:
            print("[YourNew] API key required")
            return []
        
        results = []
        
        try:
            # Make API request
            response = self._make_request(
                f"{self.base_url}/search",
                params={
                    "q": query,
                    "limit": max_results
                }
            )
            
            # Parse response
            for item in response.get("results", []):
                results.append(self._parse_publication(item))
        
        except Exception as e:
            print(f"[YourNew] Error: {e}")
        
        return results
    
    def _parse_publication(self, item: Dict) -> Dict[str, Any]:
        """Convert API response to standard format."""
        return {
            "title": item.get("title", ""),
            "authors": [a["name"] for a in item.get("authors", [])],
            "year": item.get("publicationYear"),
            "abstract": item.get("abstract", ""),
            "doi": item.get("doi"),
            "citations": item.get("citationCount", 0),
            "source": "YourNew",
            "url": item.get("url", ""),
        }
```

### 3. Register Crawler

Add to `bibliometric_crawler.py`:

```python
from crawlers import YourNewCrawler

class BibliometricCrawler:
    def __init__(self):
        # ... existing code ...
        self.crawlers = {
            # ... existing crawlers ...
            "yournew": YourNewCrawler(os.getenv("YOURNEW_API_KEY")),
        }
```

### 4. Add Tests

Add to `test_crawlers.py`:

```python
def test_yournew_crawler():
    """Test YourNew crawler instantiation and search."""
    crawler = YourNewCrawler()
    assert crawler is not None
    
    results = crawler.search("test", max_results=5)
    assert isinstance(results, list)
```

### 5. Update Documentation

Update these files:
- `README.md` - Add to list of supported sources
- `.env.example` - Add API key placeholder
- `API_INTEGRATION_GUIDE.md` - Add integration details

### 6. Submit PR

Create a pull request with:
- Crawler implementation
- Tests
- Documentation updates
- Example usage

## Documentation

### Documentation Updates

When adding features:
- Update relevant README sections
- Add inline code comments for complex logic
- Create examples in docstrings
- Update API_INTEGRATION_GUIDE.md for data sources

### Writing Good Documentation

**DO:**
- Use clear, concise language
- Provide working examples
- Include expected output
- Explain the "why" not just the "what"

**DON'T:**
- Assume prior knowledge
- Use unexplained jargon
- Leave out error cases
- Write outdated information

## Community

### Getting Help

- **Documentation**: Check README.md and guides
- **Issues**: Search existing issues on GitHub
- **Discussions**: Use GitHub Discussions for questions
- **Contact**: Open an issue for project-related queries

### Recognition

Contributors are recognized in:
- GitHub contributors list
- Release notes for significant contributions
- Special mentions in documentation

Thank you for contributing to Simple-bibliometric! 🎉
