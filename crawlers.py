"""
API Crawlers for various academic databases.
Each crawler implements actual API integrations based on official documentation.
"""

import os
import random
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import requests

# Optional: Prefer package-based clients when available to avoid requiring API keys
# (These are used as fallbacks and are not mandatory; existing HTTP-based code remains as a fallback)
try:
    from Bio import Entrez

    BIOPYTHON_AVAILABLE = True
except Exception:
    Entrez = None
    BIOPYTHON_AVAILABLE = False

try:
    import pubchempy as pcp

    PUBCHEMPY_AVAILABLE = True
except Exception:
    pcp = None
    PUBCHEMPY_AVAILABLE = False

try:
    from habanero import Crossref

    CROSSREF_AVAILABLE = True
except Exception:
    Crossref = None
    CROSSREF_AVAILABLE = False

try:
    from cerebras.cloud.sdk import Cerebras

    CEREBRAS_AVAILABLE = True
except Exception:
    Cerebras = None
    CEREBRAS_AVAILABLE = False

try:
    import pybliometrics
    from pybliometrics.scopus import ScopusSearch, AbstractRetrieval
    from pybliometrics.sciencedirect import ScienceDirectSearch, ArticleRetrieval

    PYBLIOMETRICS_AVAILABLE = True
    _pybliometrics_initialized = False
    _pybliometrics_lock = threading.Lock()
except Exception:
    pybliometrics = None
    PYBLIOMETRICS_AVAILABLE = False
    _pybliometrics_initialized = False
    _pybliometrics_lock = None

try:
    from springernature_api_client.openaccess import OpenAccessAPI
    from springernature_api_client.meta import MetaAPI
    
    SPRINGER_AVAILABLE = True
except Exception:
    OpenAccessAPI = None
    MetaAPI = None
    SPRINGER_AVAILABLE = False

# IEEE Xplore - package not available on PyPI
# Note: xploreapi package does not exist on PyPI as of 2024
# For IEEE integration, consider using requests library directly
XPLORE = None
IEEE_AVAILABLE = False

try:
    from ebscopy import edsapi
    
    EBSCO_AVAILABLE = True
except Exception:
    edsapi = None
    EBSCO_AVAILABLE = False


class BaseCrawler(ABC):
    """Base class for all academic database crawlers"""

    # Subclasses may set the associated environment variable name for better diagnostics
    env_var: Optional[str] = None

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.base_url = ""
        self.last_request_time = None
        self.requests_per_second = 3  # Conservative default

        # Retry & backoff configuration (can be adjusted per-crawler instance)
        # max_retries: number of total attempts (includes first attempt)
        self.max_retries = 3
        # base seconds used for exponential backoff (sleep = base * 2^(attempt-1))
        self.retry_backoff_base = 1.0
        # relative jitter applied to backoff (fraction in [-jitter, +jitter])
        self.retry_backoff_jitter = 0.2

    @abstractmethod
    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """Search the database with the given query"""
        pass

    def _rate_limit(self):
        """Implement rate limiting to respect API quotas"""
        if self.last_request_time:
            elapsed = time.time() - self.last_request_time
            sleep_time = (1.0 / self.requests_per_second) - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
        self.last_request_time = time.time()

    def _make_request(
        self, endpoint: str, params: Dict[str, Any] = None, method: str = "GET"
    ) -> Dict[str, Any]:
        """Make HTTP request to the API with retries and exponential backoff (with jitter).

        Behavior:
        - Applies per-instance rate limiting via self._rate_limit().
        - Retries transient errors (network errors and 5xx responses) up to self.max_retries times.
        - Does not retry on client errors (HTTP 4xx).
        - Uses an exponential backoff with configurable base and jitter (self.retry_backoff_base and self.retry_backoff_jitter).
        """
        self._rate_limit()

        headers = self._get_headers()
        url = f"{self.base_url}{endpoint}"

        attempt = 0
        last_exc = None
        max_retries = getattr(self, "max_retries", 3)
        backoff_base = getattr(self, "retry_backoff_base", 1.0)
        jitter_factor = getattr(self, "retry_backoff_jitter", 0.1)

        while attempt < max_retries:
            try:
                if method == "GET":
                    response = requests.get(
                        url, params=params, headers=headers, timeout=30
                    )
                else:
                    response = requests.post(
                        url, json=params, headers=headers, timeout=30
                    )

                response.raise_for_status()

                # Handle different response types
                content_type = response.headers.get("Content-Type", "")
                if "json" in content_type:
                    return response.json()
                elif "xml" in content_type:
                    return {"xml_content": response.text}
                else:
                    return {"content": response.text}

            except requests.exceptions.HTTPError as e:
                # For HTTP errors, check status. Do not retry on 4xx (client) errors.
                status = None
                resp_text = None
                try:
                    status = e.response.status_code
                    resp_text = e.response.text
                except Exception:
                    pass
                if status and 400 <= status < 500:
                    # Provide enhanced diagnostics for auth/client errors and return error payload
                    env_info = None
                    if getattr(self, "env_var", None):
                        env_info = (getattr(self, "env_var"), bool(os.getenv(getattr(self, "env_var"))))
                    print(
                        f"[{self.__class__.__name__}] HTTP error (status {status}): {e}."
                        + (f" Env var {env_info[0]} present: {env_info[1]}." if env_info else "")
                        + (f" Response: {resp_text[:200]}" if resp_text else "")
                    )
                    # Return structured error information so callers (and validate_keys) can inspect status/text
                    return {"error": {"status": status, "text": resp_text}}
                last_exc = e
            except requests.exceptions.RequestException as e:
                # Network or connection-level errors (retryable)
                last_exc = e
            except Exception as e:
                # Unexpected error (treat as retryable once)
                last_exc = e

            attempt += 1
            if attempt >= max_retries:
                break

            # Exponential backoff with jitter
            sleep = backoff_base * (2 ** (attempt - 1))
            # Apply relative jitter in [-jitter_factor, +jitter_factor]
            jitter = jitter_factor * (2 * random.random() - 1)
            sleep = max(0.0, sleep * (1.0 + jitter))
            time.sleep(sleep)

        # All attempts exhausted
        if last_exc:
            print(
                f"[{self.__class__.__name__}] Request failed after {attempt} attempts: {last_exc}"
            )
        return {}

    def _get_headers(self) -> Dict[str, str]:
        """Get headers for API requests"""
        headers = {
            "Accept": "application/json",
            "User-Agent": "BibliometricCrawler/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


class WoSCrawler(BaseCrawler):
    """Web of Science Starter API Crawler

    Uses official Clarivate WoS Starter API v1 client library.
    API Documentation: https://developer.clarivate.com/apis/wos-starter
    Client Repository: https://github.com/clarivate/wosstarter_python_client
    """

    env_var = "WOS_API_KEY"

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        # Note: Base URL not used; client handles it internally
        self.base_url = "https://api.clarivate.com/apis/wos-starter/v1"
        self.requests_per_second = 5  # WoS Starter API allows 5 req/sec
        self._client = None
        self._api_instance = None

    def _get_client(self):
        """Initialize and return the official Clarivate API client."""
        if self._api_instance is not None:
            return self._api_instance

        try:
            import clarivate.wos_starter.client

            # Configure API client
            config = clarivate.wos_starter.client.Configuration(
                host=self.base_url
            )
            config.api_key['ClarivateApiKeyAuth'] = self.api_key

            # Create client and API instance
            self._client = clarivate.wos_starter.client.ApiClient(config)
            self._api_instance = clarivate.wos_starter.client.DocumentsApi(
                self._client
            )
            return self._api_instance
        except ImportError:
            print(
                "[WoS] Official Clarivate client not installed. "
                "Install with: pip install git+https://github.com/clarivate/wosstarter_python_client.git"
            )
            return None
        except Exception as e:
            print(f"[WoS] Failed to initialize client: {e}")
            return None

    def _get_headers(self) -> Dict[str, str]:
        """Override headers for WoS Starter API

        Note: Official client handles headers internally.
        This method is provided for consistency with other crawlers.
        """
        headers = {
            "Accept": "application/json",
            "User-Agent": "BibliometricCrawler/1.0",
        }
        if self.api_key:
            headers["X-ApiKey"] = self.api_key
        return headers

    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """Search Web of Science Starter database using official client.

        Uses Web of Science Query Language (e.g., "TI=(cancer)" for title search)
        """
        print(f"[WoS] Searching for: {query}")

        if not self.api_key:
            print("[WoS] API key required")
            return []

        api_instance = self._get_client()
        if api_instance is None:
            print("[WoS] Failed to initialize API client")
            return []

        try:
            from clarivate.wos_starter.client.rest import ApiException

            # Convert simple query to WoS Query Language if needed
            # Default to topic search if no field tag provided
            if "=" not in query:
                wos_query = f"TS=({query})"
            else:
                wos_query = query

            # Call the official client
            response = api_instance.documents_get(
                q=wos_query,
                db="WOS",
                limit=min(max_results, 50),  # Max 50 per request
                page=1,
                sort_field="TC+D",  # Sort by Times Cited descending
            )

            if not response or not hasattr(response, "hits") or not response.hits:
                return []

            results = []
            for hit in response.hits:
                # Extract data from official client response
                title = hit.title if hasattr(hit, "title") else ""
                authors = []
                if hasattr(hit, "names") and hit.names:
                    authors = [
                        author.full_name
                        for author in hit.names
                        if hasattr(author, "full_name")
                    ]

                year = str(hit.year) if hasattr(hit, "year") else ""
                doi = (
                    hit.identifiers.doi
                    if hasattr(hit, "identifiers")
                    and hasattr(hit.identifiers, "doi")
                    else ""
                )
                uid = hit.uid if hasattr(hit, "uid") else ""

                # Extract citations
                citations = 0
                if hasattr(hit, "citations") and hit.citations:
                    try:
                        for citation in hit.citations:
                            if hasattr(citation, "count"):
                                citations = int(citation.count)
                                break
                    except (ValueError, TypeError):
                        citations = 0

                result = {
                    "title": title,
                    "authors": authors,
                    "year": year,
                    "doi": doi,
                    "abstract": "",  # Not in Starter API
                    "source": "WoS",
                    "citations": citations,
                    "url": f"https://www.webofscience.com/wos/woscc/full-record/{uid}",
                }
                results.append(result)

            return results

        except ApiException as e:
            if e.status == 401:
                print(
                    "[WoS] Authentication failed: Invalid API key or expired token"
                )
            else:
                print(
                    f"[WoS] API error (status {e.status}): {e.reason if hasattr(e, 'reason') else str(e)}"
                )
            return []
        except Exception as e:
            print(f"[WoS] Error during search: {e}")
            return []


class ScopusCrawler(BaseCrawler):
    """Scopus API Crawler

    Uses the official pybliometrics library which wraps Elsevier's Scopus API.
    API Documentation: https://pybliometrics.readthedocs.io/en/stable/
    """

    env_var = "SCOPUS_API_KEY"

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        # pybliometrics handles config automatically via ~/.config/pybliometrics.cfg
        # API key is not directly used in initialization; pybliometrics manages auth
        self.use_pybliometrics = PYBLIOMETRICS_AVAILABLE

    def _initialize_pybliometrics(self) -> bool:
        """Initialize pybliometrics if not already done (thread-safe singleton).
        
        pybliometrics uses config file ~/.config/pybliometrics.cfg.
        Pass API keys programmatically to avoid interactive prompts.
        """
        global _pybliometrics_initialized
        
        if not self.use_pybliometrics:
            return False
            
        # Thread-safe singleton initialization
        with _pybliometrics_lock:
            if _pybliometrics_initialized:
                return True
                
            try:
                # Get API key from instance or environment
                api_key = self.api_key or os.getenv("SCOPUS_API_KEY") or os.getenv("ELS_API_KEY")
                inst_token = os.getenv("ELS_INSTTOKEN")
                
                if not api_key:
                    print("[Scopus] No API key found in environment or instance")
                    return False
                
                # Initialize pybliometrics with API keys to avoid interactive prompts
                keys = [api_key]
                inst_tokens = [inst_token] if inst_token else None
                
                try:
                    pybliometrics.init(keys=keys, inst_tokens=inst_tokens)
                    _pybliometrics_initialized = True
                    return True
                except Exception as init_error:
                    # If initialization fails, try to diagnose the issue
                    error_msg = str(init_error)
                    if "Directories" in error_msg:
                        print(f"[Scopus] Config error: {error_msg}")
                        print("[Scopus] Try deleting ~/.config/pybliometrics.cfg and restart")
                    else:
                        print(f"[Scopus] pybliometrics initialization failed: {error_msg}")
                    return False
            except Exception as e:
                print(f"[Scopus] pybliometrics initialization failed: {e}")
                return False

    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        Search Scopus database using pybliometrics library.
        Returns a list of article metadata.
        """
        print(f"[Scopus] Searching for: {query}")

        if not self.use_pybliometrics:
            print("[Scopus] pybliometrics not available, returning empty results")
            return []

        if not self._initialize_pybliometrics():
            return []

        try:
            # ScopusSearch handles the query and pagination
            # max_results controls how many results to return
            search_results = ScopusSearch(
                query=query,
                view="COMPLETE",
                refresh=False  # Use cached results if available
            )

            results = []
            # Iterate through results (pybliometrics handles pagination internally)
            for i, article in enumerate(search_results):
                if i >= max_results:
                    break

                try:
                    # article is a namedtuple with scopus metadata
                    result = {
                        "title": getattr(article, "title", ""),
                        "authors": [getattr(article, "author_names", "")]
                        if hasattr(article, "author_names")
                        else [],
                        "year": str(getattr(article, "coverDate", ""))[:4]
                        if hasattr(article, "coverDate")
                        else "",
                        "doi": getattr(article, "doi", ""),
                        "abstract": getattr(article, "description", ""),
                        "source": "Scopus",
                        "citations": int(getattr(article, "citedby_count", 0))
                        if hasattr(article, "citedby_count")
                        else 0,
                        "url": getattr(article, "url", ""),
                        "journal": getattr(article, "publicationName", ""),
                        "issn": getattr(article, "issn", ""),
                        "scopus_id": getattr(article, "eid", ""),
                    }
                    results.append(result)
                except Exception as e:
                    print(f"[Scopus] Error parsing article {i}: {e}")
                    continue

            return results

        except Exception as e:
            print(f"[Scopus] Error during search: {e}")
            return []


class ScienceDirectCrawler(BaseCrawler):
    """ScienceDirect API Crawler

    Uses the official pybliometrics library which wraps Elsevier's ScienceDirect API.
    API Documentation: https://pybliometrics.readthedocs.io/en/stable/
    """

    env_var = "SCIENCEDIRECT_API_KEY"

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        # pybliometrics handles config automatically via ~/.config/pybliometrics.cfg
        # API key is not directly used in initialization; pybliometrics manages auth
        self.use_pybliometrics = PYBLIOMETRICS_AVAILABLE

    def _initialize_pybliometrics(self) -> bool:
        """Initialize pybliometrics if not already done (thread-safe singleton).
        
        pybliometrics uses config file ~/.config/pybliometrics.cfg.
        Pass API keys programmatically to avoid interactive prompts.
        """
        global _pybliometrics_initialized
        
        if not self.use_pybliometrics:
            return False
            
        # Thread-safe singleton initialization
        with _pybliometrics_lock:
            if _pybliometrics_initialized:
                return True
                
            try:
                # Get API key from instance or environment
                api_key = self.api_key or os.getenv("SCIENCEDIRECT_API_KEY") or os.getenv("ELS_API_KEY")
                inst_token = os.getenv("ELS_INSTTOKEN")
                
                if not api_key:
                    print("[ScienceDirect] No API key found in environment or instance")
                    return False
                
                # Initialize pybliometrics with API keys to avoid interactive prompts
                keys = [api_key]
                inst_tokens = [inst_token] if inst_token else None
                
                try:
                    pybliometrics.init(keys=keys, inst_tokens=inst_tokens)
                    _pybliometrics_initialized = True
                    return True
                except Exception as init_error:
                    # If initialization fails, try to diagnose the issue
                    error_msg = str(init_error)
                    if "Directories" in error_msg:
                        print(f"[ScienceDirect] Config error: {error_msg}")
                        print("[ScienceDirect] Try deleting ~/.config/pybliometrics.cfg and restart")
                    else:
                        print(f"[ScienceDirect] pybliometrics initialization failed: {error_msg}")
                    return False
            except Exception as e:
                print(f"[ScienceDirect] pybliometrics initialization failed: {e}")
                return False

    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        Search ScienceDirect database using pybliometrics library.
        Returns a list of article metadata.
        """
        print(f"[ScienceDirect] Searching for: {query}")

        if not self.use_pybliometrics:
            print("[ScienceDirect] pybliometrics not available, returning empty results")
            return []

        if not self._initialize_pybliometrics():
            return []

        try:
            # ScienceDirectSearch handles the query
            # max_results controls how many results to return
            # Note: ScienceDirect API only supports 'STANDARD' view parameter
            search_results = ScienceDirectSearch(
                query=query,
                view="STANDARD",
                refresh=False  # Use cached results if available
            )

            results = []
            # Iterate through results
            for i, article in enumerate(search_results):
                if i >= max_results:
                    break

                try:
                    # article is a namedtuple with ScienceDirect metadata
                    result = {
                        "title": getattr(article, "title", ""),
                        "authors": [getattr(article, "author_names", "")]
                        if hasattr(article, "author_names")
                        else [],
                        "year": str(getattr(article, "coverDate", ""))[:4]
                        if hasattr(article, "coverDate")
                        else "",
                        "doi": getattr(article, "doi", ""),
                        "abstract": getattr(article, "description", ""),
                        "source": "ScienceDirect",
                        "citations": 0,  # ScienceDirect API doesn't provide citation counts
                        "url": getattr(article, "url", ""),
                        "journal": getattr(article, "publicationName", ""),
                        "pii": getattr(article, "pii", ""),
                    }
                    results.append(result)
                except Exception as e:
                    print(f"[ScienceDirect] Error parsing article {i}: {e}")
                    continue

            return results

        except Exception as e:
            print(f"[ScienceDirect] Error during search: {e}")
            return []


class PubMedCrawler(BaseCrawler):
    """PubMed API Crawler

    API Documentation: https://www.ncbi.nlm.nih.gov/home/develop/api/
    """

    env_var = "PUBMED_API_KEY"

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        self.requests_per_second = 3 if not api_key else 10

    def _get_headers(self) -> Dict[str, str]:
        """Override headers for NCBI API"""
        headers = {
            "Accept": "application/json",
            "User-Agent": "BibliometricCrawler/1.0",
        }
        return headers

    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        Search PubMed database using Biopython Entrez when available (fallback to REST)
        """
        print(f"[PubMed] Searching for: {query}")

        # Try Biopython Entrez if available
        if BIOPYTHON_AVAILABLE and Entrez is not None:
            try:
                # Recommended: set contact email for Entrez usage
                Entrez.email = os.getenv(
                    "NCBI_EMAIL", getattr(Entrez, "email", "") or ""
                )
                if self.api_key:
                    Entrez.api_key = self.api_key

                # Step 1: Search for IDs
                search_handle = Entrez.esearch(
                    db="pubmed",
                    term=query,
                    retmax=min(max_results, 10000),
                    retmode="xml",
                )
                search_results = Entrez.read(search_handle)
                id_list = search_results.get("IdList", [])
                if not id_list:
                    return []

                # Step 2: Fetch article XML for summaries in batches
                results = []
                batch_size = 500

                for i in range(0, len(id_list), batch_size):
                    batch_ids = id_list[i : i + batch_size]
                    ef_handle = Entrez.efetch(
                        db="pubmed", id=",".join(batch_ids), retmode="xml"
                    )
                    xml_text = (
                        ef_handle.read() if hasattr(ef_handle, "read") else ef_handle
                    )

                    import xml.etree.ElementTree as ET

                    root = ET.fromstring(xml_text)
                    for article in root.findall(".//PubmedArticle"):
                        try:
                            pmid_el = article.find(".//PMID")
                            pmid = pmid_el.text if pmid_el is not None else ""
                            title_el = article.find(".//ArticleTitle")
                            title = (
                                "".join(title_el.itertext()).strip()
                                if title_el is not None
                                else ""
                            )

                            # Authors
                            authors = []
                            for a in article.findall(".//AuthorList/Author"):
                                if a.find("CollectiveName") is not None:
                                    name = a.find("CollectiveName").text
                                else:
                                    fore = a.find("ForeName")
                                    last = a.find("LastName")
                                    initials = (
                                        a.find("Initials").text
                                        if a.find("Initials") is not None
                                        else ""
                                    )
                                    if fore is not None and last is not None:
                                        name = f"{fore.text} {last.text}"
                                    elif last is not None:
                                        name = last.text
                                    else:
                                        name = initials or ""
                                if name:
                                    authors.append(name)

                            # Year
                            year = ""
                            pubdate = article.find(".//PubDate")
                            if pubdate is not None:
                                year_el = pubdate.find("Year")
                                medline_date = pubdate.find("MedlineDate")
                                if year_el is not None and year_el.text:
                                    year = year_el.text
                                elif medline_date is not None and medline_date.text:
                                    year = medline_date.text.split()[0]

                            # DOI
                            doi = ""
                            for aid in article.findall(".//ArticleIdList/ArticleId"):
                                if aid.get("IdType") == "doi":
                                    doi = aid.text
                                    break

                            journal_el = article.find(".//Journal/Title")
                            journal = journal_el.text if journal_el is not None else ""

                            result = {
                                "title": title,
                                "authors": authors,
                                "year": year,
                                "doi": doi or "",
                                "abstract": "",  # Abstracts may require separate efetch parsing
                                "source": "PubMed",
                                "citations": 0,
                                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
                                if pmid
                                else "",
                                "pmid": pmid,
                                "journal": journal,
                                "publication_types": [],
                            }
                            results.append(result)
                        except Exception:
                            # Best-effort: skip problematic article and continue
                            continue

                return results
            except Exception as e:
                print(f"[PubMed] Entrez (biopython) error: {e} -- falling back to REST")

        # REST fallback (existing implementation)
        try:
            # Step 1: Search for IDs
            search_params = {
                "db": "pubmed",
                "term": query,
                "retmax": min(max_results, 10000),
                "retmode": "json",
            }
            if self.api_key:
                search_params["api_key"] = self.api_key

            search_response = self._make_request("esearch.fcgi", params=search_params)

            if not search_response or "esearchresult" not in search_response:
                return []

            id_list = search_response.get("esearchresult", {}).get("idlist", [])

            if not id_list:
                return []

            # Step 2: Fetch summaries for the IDs (batch of 500 max)
            results = []
            batch_size = 500

            for i in range(0, len(id_list), batch_size):
                batch_ids = id_list[i : i + batch_size]

                summary_params = {
                    "db": "pubmed",
                    "id": ",".join(batch_ids),
                    "retmode": "json",
                }
                if self.api_key:
                    summary_params["api_key"] = self.api_key

                summary_response = self._make_request(
                    "esummary.fcgi", params=summary_params
                )

                if not summary_response or "result" not in summary_response:
                    continue

                result_data = summary_response.get("result", {})

                for pmid in batch_ids:
                    if pmid not in result_data:
                        continue

                    doc = result_data[pmid]

                    # Extract authors
                    authors = []
                    for author in doc.get("authors", []):
                        if "name" in author:
                            authors.append(author["name"])

                    result = {
                        "title": doc.get("title", ""),
                        "authors": authors,
                        "year": doc.get("pubdate", "")[:4]
                        if doc.get("pubdate")
                        else "",
                        "doi": doc.get("elocationid", "").replace("doi: ", "")
                        if "doi:" in doc.get("elocationid", "")
                        else "",
                        "abstract": "",
                        "source": "PubMed",
                        "citations": 0,
                        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        "pmid": pmid,
                        "journal": doc.get("source", ""),
                        "publication_types": doc.get("pubtype", []),
                    }
                    results.append(result)

            return results

        except Exception as e:
            print(f"[PubMed] Error during search: {e}")
            return []


class PubChemCrawler(BaseCrawler):
    """PubChem API Crawler

    API Documentation: https://www.ncbi.nlm.nih.gov/home/develop/api/
    """

    env_var = "PUBCHEM_API_KEY"

    def __init__(self, api_key: Optional[str] = None):
        # PubChem typically does not need an API key (public data) but we accept one if provided
        super().__init__(api_key)
        self.base_url = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/"
        self.requests_per_second = 5

    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        Search PubChem database using PUG REST API or the pubchempy package if available
        """
        print(f"[PubChem] Searching for: {query}")

        try:
            # Prefer pubchempy package when available (no API key required)
            if PUBCHEMPY_AVAILABLE and pcp is not None:
                try:
                    compounds = pcp.get_compounds(query, "name")
                    if not compounds:
                        return []
                    compounds = compounds[:max_results]
                    results = []
                    for comp in compounds:
                        cid = getattr(comp, "cid", None)
                        iupac = getattr(comp, "iupac_name", None) or (
                            comp.synonyms[0] if getattr(comp, "synonyms", []) else None
                        )
                        result = {
                            "title": iupac or f"Compound CID:{cid}",
                            "authors": [],
                            "year": "",
                            "doi": "",
                            "abstract": f"Molecular Formula: {getattr(comp, 'molecular_formula', '')}, MW: {getattr(comp, 'molecular_weight', '')}",
                            "source": "PubChem",
                            "citations": 0,
                            "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"
                            if cid
                            else "",
                            "cid": cid,
                            "molecular_formula": getattr(comp, "molecular_formula", ""),
                            "molecular_weight": getattr(comp, "molecular_weight", ""),
                        }
                        results.append(result)
                    return results
                except Exception as e:
                    print(f"[PubChem] pubchempy error, falling back to PUG REST: {e}")

            # Fallback to PUG REST API
            endpoint = f"compound/name/{query}/cids/JSON"
            # Use default PUG REST response (no extra params) to be more robust
            response = self._make_request(endpoint)

            if not response or "IdentifierList" not in response:
                return []

            cids = response.get("IdentifierList", {}).get("CID", [])

            if not cids:
                return []

            # Limit results
            cids = cids[:max_results]

            results = []

            # Get properties for each compound
            for cid in cids:
                try:
                    props_endpoint = f"compound/cid/{cid}/property/MolecularFormula,MolecularWeight,IUPACName/JSON"
                    props_response = self._make_request(props_endpoint)

                    if props_response and "PropertyTable" in props_response:
                        props = props_response["PropertyTable"]["Properties"][0]

                        result = {
                            "title": props.get("IUPACName", f"Compound CID:{cid}"),
                            "authors": [],
                            "year": "",
                            "doi": "",
                            "abstract": f"Molecular Formula: {props.get('MolecularFormula', '')}, MW: {props.get('MolecularWeight', '')}",
                            "source": "PubChem",
                            "citations": 0,
                            "url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
                            "cid": cid,
                            "molecular_formula": props.get("MolecularFormula", ""),
                            "molecular_weight": props.get("MolecularWeight", ""),
                        }
                        results.append(result)
                except Exception as e:
                    print(f"[PubChem] Error fetching CID {cid}: {e}")
                    continue

            return results

        except Exception as e:
            print(f"[PubChem] Error during search: {e}")
            return []


class GeneCrawler(BaseCrawler):
    """NCBI Gene Database API Crawler

    API Documentation: https://www.ncbi.nlm.nih.gov/home/develop/api/
    """

    env_var = "GENE_API_KEY"

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        self.requests_per_second = 3 if not api_key else 10

    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        Search Gene database using Biopython Entrez when available (fallback to REST)
        """
        print(f"[Gene] Searching for: {query}")

        # Try Biopython Entrez first
        if BIOPYTHON_AVAILABLE and Entrez is not None:
            try:
                Entrez.email = os.getenv(
                    "NCBI_EMAIL", getattr(Entrez, "email", "") or ""
                )
                if self.api_key:
                    Entrez.api_key = self.api_key

                search_handle = Entrez.esearch(
                    db="gene",
                    term=query,
                    retmax=min(max_results, 10000),
                    retmode="xml",
                )
                search_results = Entrez.read(search_handle)
                id_list = search_results.get("IdList", [])
                if not id_list:
                    return []

                # Fetch summaries (batch up to 500)
                batch_ids = id_list[: min(len(id_list), 500)]
                summary_handle = Entrez.esummary(
                    db="gene", id=",".join(batch_ids), retmode="xml"
                )
                summaries = Entrez.read(summary_handle)

                docs = []
                if isinstance(summaries, dict):
                    if "DocumentSummarySet" in summaries:
                        docs = summaries.get("DocumentSummarySet", {}).get(
                            "DocumentSummary", []
                        )
                    elif "result" in summaries:
                        rd = summaries.get("result", {})
                        for gid in batch_ids:
                            if gid in rd:
                                docs.append(rd[gid])
                elif isinstance(summaries, list):
                    docs = summaries

                results = []
                for doc in docs[:max_results]:
                    # Support different key naming conventions returned by Entrez
                    title = doc.get("Name", "") if isinstance(doc, dict) else ""
                    description = (
                        doc.get("Description", "") if isinstance(doc, dict) else ""
                    )
                    organism = ""
                    org = doc.get("Organism", {}) if isinstance(doc, dict) else {}
                    if isinstance(org, dict):
                        organism = org.get("ScientificName", "") or org.get(
                            "scientificname", ""
                        )

                    gene_id = doc.get("Id", "") if isinstance(doc, dict) else ""

                    result = {
                        "title": title,
                        "authors": [],
                        "year": "",
                        "doi": "",
                        "abstract": description,
                        "source": "NCBI Gene",
                        "citations": 0,
                        "url": f"https://www.ncbi.nlm.nih.gov/gene/{gene_id}"
                        if gene_id
                        else "",
                        "gene_id": gene_id,
                        "organism": organism,
                        "chromosome": doc.get("Chromosome", "")
                        if isinstance(doc, dict)
                        else "",
                    }
                    results.append(result)

                return results
            except Exception as e:
                print(f"[Gene] Entrez (biopython) error: {e} -- falling back to REST")

        # Fallback: existing REST-based implementation
        try:
            search_params = {
                "db": "gene",
                "term": query,
                "retmax": min(max_results, 10000),
                "retmode": "json",
            }
            if self.api_key:
                search_params["api_key"] = self.api_key

            search_response = self._make_request("esearch.fcgi", params=search_params)

            if not search_response or "esearchresult" not in search_response:
                return []

            id_list = search_response.get("esearchresult", {}).get("idlist", [])

            if not id_list:
                return []

            # Fetch summaries
            summary_params = {
                "db": "gene",
                "id": ",".join(id_list[: min(len(id_list), 500)]),
                "retmode": "json",
            }
            if self.api_key:
                summary_params["api_key"] = self.api_key

            summary_response = self._make_request(
                "esummary.fcgi", params=summary_params
            )

            if not summary_response or "result" not in summary_response:
                return []

            result_data = summary_response.get("result", {})
            results = []

            for gene_id in id_list[:max_results]:
                if gene_id not in result_data:
                    continue

                doc = result_data[gene_id]

                result = {
                    "title": doc.get("name", ""),
                    "authors": [],
                    "year": "",
                    "doi": "",
                    "abstract": doc.get("description", ""),
                    "source": "NCBI Gene",
                    "citations": 0,
                    "url": f"https://www.ncbi.nlm.nih.gov/gene/{gene_id}",
                    "gene_id": gene_id,
                    "organism": doc.get("organism", {}).get("scientificname", ""),
                    "chromosome": doc.get("chromosome", ""),
                }
                results.append(result)

            return results

        except Exception as e:
            print(f"[Gene] Error during search: {e}")
            return []


class GenomeCrawler(BaseCrawler):
    """NCBI Genome Database API Crawler

    API Documentation: https://www.ncbi.nlm.nih.gov/home/develop/api/
    """

    env_var = "GENOME_API_KEY"

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        self.requests_per_second = 3 if not api_key else 10

    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        Search Genome database using Biopython Entrez when available (fallback to REST)
        """
        print(f"[Genome] Searching for: {query}")

        if BIOPYTHON_AVAILABLE and Entrez is not None:
            try:
                Entrez.email = os.getenv(
                    "NCBI_EMAIL", getattr(Entrez, "email", "") or ""
                )
                if self.api_key:
                    Entrez.api_key = self.api_key

                handle = Entrez.esearch(
                    db="genome",
                    term=query,
                    retmax=min(max_results, 10000),
                    retmode="xml",
                )
                search_results = Entrez.read(handle)
                id_list = search_results.get("IdList", [])
                if not id_list:
                    return []

                results = []
                for genome_id in id_list[:max_results]:
                    result = {
                        "title": f"Genome ID: {genome_id}",
                        "authors": [],
                        "year": "",
                        "doi": "",
                        "abstract": "",
                        "source": "NCBI Genome",
                        "citations": 0,
                        "url": f"https://www.ncbi.nlm.nih.gov/genome/{genome_id}",
                        "genome_id": genome_id,
                    }
                    results.append(result)

                return results
            except Exception as e:
                print(f"[Genome] Entrez (biopython) error: {e} -- falling back to REST")

        # Fallback: existing REST-based implementation
        try:
            search_params = {
                "db": "genome",
                "term": query,
                "retmax": min(max_results, 10000),
                "retmode": "json",
            }
            if self.api_key:
                search_params["api_key"] = self.api_key

            search_response = self._make_request("esearch.fcgi", params=search_params)

            if not search_response or "esearchresult" not in search_response:
                return []

            id_list = search_response.get("esearchresult", {}).get("idlist", [])

            if not id_list:
                return []

            results = []

            for genome_id in id_list[:max_results]:
                result = {
                    "title": f"Genome ID: {genome_id}",
                    "authors": [],
                    "year": "",
                    "doi": "",
                    "abstract": "",
                    "source": "NCBI Genome",
                    "citations": 0,
                    "url": f"https://www.ncbi.nlm.nih.gov/genome/{genome_id}",
                    "genome_id": genome_id,
                }
                results.append(result)

            return results

        except Exception as e:
            print(f"[Genome] Error during search: {e}")
            return []


class SAGECrawler(BaseCrawler):
    """SAGE Journals API Crawler (via CrossRef)

    API Documentation: https://api.crossref.org/swagger-ui/index.html
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.base_url = "https://api.crossref.org/works"
        self.requests_per_second = 1

    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        Search SAGE journals via CrossRef API or via the habanero Crossref client if available.
        Filters results to SAGE publications.
        """
        print(f"[SAGE] Searching for: {query}")

        try:
            items = []

            # Prefer habanero Crossref client when available (no API key required)
            if CROSSREF_AVAILABLE and Crossref is not None:
                try:
                    cr = Crossref()
                    # Don't pass a raw 'filter' string to habanero's client (it expects filter values
                    # as dict/list and can raise on unsupported formats). Instead, request a larger
                    # set of results and apply a local publisher/container-title filter for SAGE.
                    response = cr.works(
                        query=query,
                        limit=min(max(max_results * 20, 200), 1000),
                    )
                    if isinstance(response, dict):
                        items = response.get("message", {}).get("items", [])
                    else:
                        items = response.get("message", {}).get("items", [])
                    # Filter locally for SAGE publisher (case-insensitive) to avoid relying on a
                    # CrossRef server-side 'publisher-name' filter which may not be supported.
                    items = [
                        it
                        for it in items
                        if (
                            "publisher" in it
                            and "sage" in (it.get("publisher") or "").lower()
                        )
                        or any(
                            "sage" in (ct or "").lower()
                            for ct in it.get("container-title", [])
                        )
                    ]
                except Exception as e:
                    print(
                        f"[SAGE] habanero Crossref error, falling back to REST API: {e}"
                    )

            # Fallback to REST-based CrossRef endpoint if habanero isn't available or returned nothing
            if not items:
                params = {
                    "query": query,
                    "rows": min(max(200, max_results * 20), 1000),
                }

                response = self._make_request("", params=params)

                if not response or "message" not in response:
                    return []

                items = response.get("message", {}).get("items", [])

                # Filter items locally for SAGE publications (check publisher and container-title)
                filtered_items = []
                for it in items:
                    publisher = (it.get("publisher") or "").lower()
                    container_titles = [
                        ct.lower() for ct in (it.get("container-title") or []) if ct
                    ]
                    if "sage" in publisher or any(
                        "sage" in ct for ct in container_titles
                    ):
                        filtered_items.append(it)
                items = filtered_items

            results = []

            for item in items:
                # Extract authors (preserve name, ORCID, and affiliation when available)
                authors = []
                for author in item.get("author", []):
                    given = author.get("given", "")
                    family = author.get("family", "")
                    full_name = f"{given} {family}".strip()
                    # Try to extract ORCID and affiliations when present in the CrossRef author object
                    orcid = None
                    affs: List[str] = []
                    if isinstance(author, dict):
                        # ORCID may be present as 'ORCID' or 'orcid' or as a URI
                        orcid = author.get("ORCID") or author.get("orcid")
                        if orcid and isinstance(orcid, str) and "orcid.org" in orcid:
                            orcid = orcid.split("/")[-1]
                        # affiliation can be a list of dicts or strings
                        raw_aff = author.get("affiliation", []) or []
                        for a in raw_aff:
                            if isinstance(a, dict):
                                if a.get("name"):
                                    affs.append(a.get("name"))
                            elif isinstance(a, str):
                                affs.append(a)
                    # Always include the name; attach metadata where available
                    if full_name:
                        authors.append(
                            {"name": full_name, "orcid": orcid, "affiliation": affs}
                        )

                # Extract publication year (support both 'issued' and 'published-print' structures)
                pub_date = item.get(
                    "issued",
                    item.get("published-print", item.get("published-online", {})),
                )
                year = ""
                if pub_date and "date-parts" in pub_date:
                    date_parts = pub_date["date-parts"][0]
                    if date_parts:
                        year = str(date_parts[0])

                result = {
                    "title": item.get("title", [""])[0] if item.get("title") else "",
                    "authors": authors,
                    "year": year,
                    "doi": item.get("DOI", ""),
                    "abstract": item.get("abstract", ""),
                    "source": "SAGE",
                    "citations": item.get("is-referenced-by-count", 0),
                    "url": f"https://doi.org/{item.get('DOI', '')}"
                    if item.get("DOI")
                    else "",
                    "journal": item.get("container-title", [""])[0]
                    if item.get("container-title")
                    else "",
                }
                results.append(result)

            return results

        except Exception as e:
            print(f"[SAGE] Error during search: {e}")
            return []


class IEEECrawler(BaseCrawler):
    """IEEE Xplore API Crawler

    Uses the official xploreapi Python SDK.
    API Documentation: https://developer.ieee.org/Python3_Software_Development_Kit
    """

    env_var = "IEEE_API_KEY"

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.use_ieee = IEEE_AVAILABLE
        self.requests_per_second = 1

    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        Search IEEE Xplore database using official SDK
        """
        print(f"[IEEE] Searching for: {query}")

        if not self.use_ieee:
            print("[IEEE] xploreapi not available")
            return []

        api_key = self.api_key or os.getenv("IEEE_API_KEY")
        if not api_key:
            print("[IEEE] API key required")
            return []

        try:
            # Initialize XPLORE API client
            query_obj = XPLORE(api_key)
            
            # Set query parameters
            query_obj.queryText(query)
            query_obj.maximumResults(min(max_results, 200))  # Max 200 per request
            query_obj.dataType('json')
            query_obj.dataFormat('object')
            
            # Execute search
            response = query_obj.callAPI()

            results = []
            if response and 'articles' in response:
                for article in response['articles']:
                    # Extract authors
                    authors = []
                    if 'authors' in article and 'authors' in article['authors']:
                        for author in article['authors']['authors']:
                            full_name = author.get("full_name", "")
                            if full_name:
                                authors.append(full_name)

                    result = {
                        "title": article.get("title", ""),
                        "authors": authors,
                        "year": str(article.get("publication_year", "")),
                        "doi": article.get("doi", ""),
                        "abstract": article.get("abstract", ""),
                        "source": "IEEE",
                        "citations": article.get("citing_paper_count", 0),
                        "url": article.get("html_url", ""),
                        "journal": article.get("publication_title", ""),
                        "isbn": article.get("isbn", ""),
                        "issn": article.get("issn", ""),
                        "article_number": article.get("article_number", ""),
                    }
                    results.append(result)

            return results

        except Exception as e:
            print(f"[IEEE] Error during search: {e}")
            return []


class ERICCrawler(BaseCrawler):
    """ERIC (Education Resources Information Center) API Crawler

    API Documentation: https://eric.ed.gov/?api
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.base_url = "https://api.ies.ed.gov/eric/"
        self.requests_per_second = 2  # Be respectful with rate limiting

    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        Search ERIC database
        Uses ERIC API: https://eric.ed.gov/?api
        """
        print(f"[ERIC] Searching for: {query}")

        try:
            params = {
                "search": query,
                "rows": min(max_results, 2000),  # ERIC max is 2000
                "format": "json",
                "start": 0,
            }

            response = self._make_request("", params=params)

            if not response or "response" not in response:
                return []

            docs = response.get("response", {}).get("docs", [])
            results = []

            for doc in docs:
                result = {
                    "title": doc.get("title", ""),
                    "authors": doc.get("author", []),
                    "year": doc.get("publicationdateyear", ""),
                    "doi": doc.get("doi", ""),
                    "abstract": doc.get("description", ""),
                    "source": "ERIC",
                    "citations": 0,  # ERIC doesn't provide citation count
                    "url": f"https://eric.ed.gov/?id={doc.get('id', '')}",
                    "publication_type": doc.get("publicationtype", []),
                    "source_type": doc.get("sourcetype", ""),
                }
                results.append(result)

            return results

        except Exception as e:
            print(f"[ERIC] Error during search: {e}")
            return []


class SpringerCrawler(BaseCrawler):
    """Springer Nature API Crawler

    Uses the official springernature-api-client library.
    API Documentation: https://dev.springernature.com/docs/python-api-wrapper/
    """

    env_var = "SPRINGER_API_KEY"

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.use_springer = SPRINGER_AVAILABLE
        self.requests_per_second = 0.2  # ~5000 calls/day

    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        Search Springer Nature database using official client
        """
        print(f"[Springer] Searching for: {query}")

        if not self.use_springer:
            print("[Springer] springernature-api-client not available")
            return []

        api_key = self.api_key or os.getenv("SPRINGER_API_KEY")
        if not api_key:
            print("[Springer] API key required")
            return []

        try:
            # Use OpenAccessAPI for open access content
            client = OpenAccessAPI(api_key=api_key)
            
            # Search with query
            response = client.search(
                q=query,
                p=min(max_results, 100),  # Max 100 per request
                s=1,  # Starting position
                fetch_all=False
            )

            results = []
            if response and 'records' in response:
                for record in response['records']:
                    result = {
                        "title": record.get("title", ""),
                        "authors": record.get("creators", []),
                        "year": record.get("publicationDate", "")[:4]
                        if record.get("publicationDate")
                        else "",
                        "doi": record.get("doi", ""),
                        "abstract": record.get("abstract", ""),
                        "source": "Springer",
                        "citations": 0,
                        "url": record.get("url", [{}])[0].get("value", "") if record.get("url") else "",
                        "journal": record.get("publicationName", ""),
                        "issn": record.get("issn", ""),
                    }
                    results.append(result)

            return results

        except Exception as e:
            print(f"[Springer] Error during search: {e}")
            return []


class EBSCOCrawler(BaseCrawler):
    """EBSCO Discovery Service API Crawler

    Uses the official ebscopy library.
    API Documentation: https://github.com/ebsco/ebscopy
    """

    env_var = "EBSCO_USER_ID"

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.use_ebsco = EBSCO_AVAILABLE
        self.session = None

    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        Search EBSCO Discovery Service using official client
        """
        print(f"[EBSCO] Searching for: {query}")

        if not self.use_ebsco:
            print("[EBSCO] ebscopy not available")
            return []

        # EBSCO uses user_id, password, profile, and org
        user_id = os.getenv("EBSCO_USER_ID")
        password = os.getenv("EBSCO_PASSWORD")
        profile = os.getenv("EBSCO_PROFILE", "edsapi")
        org = os.getenv("EBSCO_ORG", "")

        if not user_id or not password:
            print("[EBSCO] EBSCO_USER_ID and EBSCO_PASSWORD required")
            return []

        try:
            # Create session
            self.session = edsapi.Session(
                user_id=user_id,
                password=password,
                profile=profile,
                org=org,
                guest="n"
            )
            
            # Perform search
            search_results = self.session.search(query)

            results = []
            if search_results and hasattr(search_results, 'records'):
                for record in search_results.records[:max_results]:
                    result = {
                        "title": getattr(record, "title", ""),
                        "authors": getattr(record, "authors", []),
                        "year": getattr(record, "pub_year", ""),
                        "doi": getattr(record, "doi", ""),
                        "abstract": getattr(record, "abstract", ""),
                        "source": "EBSCO",
                        "citations": 0,
                        "url": getattr(record, "plink", ""),
                        "journal": getattr(record, "source_title", ""),
                        "issn": getattr(record, "issn", ""),
                    }
                    results.append(result)

            # End session
            self.session.end()
            return results

        except Exception as e:
            print(f"[EBSCO] Error during search: {e}")
            if self.session:
                try:
                    self.session.end()
                except:
                    pass
            return []


class WileyCrawler(BaseCrawler):
    """Wiley Online Library API Crawler

    API Documentation: https://onlinelibrary.wiley.com/library-info/resources/text-and-datamining
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.base_url = "https://api.wiley.com/onlinelibrary/tdm/v1/"

    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        Search Wiley database
        Note: Wiley TDM API requires special access and authentication
        """
        print(f"[Wiley] Searching for: {query}")

        if not self.api_key:
            print("[Wiley] API key and institutional access required")
            return []

        try:
            # Wiley uses Wiley-TDM-Client-Token header
            headers = self._get_headers()
            headers["Wiley-TDM-Client-Token"] = self.api_key

            _params = {"query": query, "max": min(max_results, 100)}

            # Note: Actual endpoint structure depends on access type
            print("[Wiley] Note: Requires institutional access for full functionality")
            return []

        except Exception as e:
            print(f"[Wiley] Error during search: {e}")
            return []
