"""
API Crawlers for various academic databases.
Each crawler implements actual API integrations based on official documentation.
"""

import os
import random
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


class BaseCrawler(ABC):
    """Base class for all academic database crawlers"""

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
                try:
                    status = e.response.status_code
                except Exception:
                    pass
                if status and 400 <= status < 500:
                    print(
                        f"[{self.__class__.__name__}] HTTP error (status {status}): {e}"
                    )
                    return {}
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
    """Web of Science API Crawler

    API Documentation: https://api.clarivate.com/swagger-ui/?apikey=none&url=https%3A%2F%2Fdeveloper.clarivate.com%2Fapis%2Fwos%2Fswagger
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.base_url = "https://api.clarivate.com/api/wos"
        self.requests_per_second = 1

    def _get_headers(self) -> Dict[str, str]:
        """Override headers for WoS API"""
        headers = {
            "Accept": "application/json",
            "User-Agent": "BibliometricCrawler/1.0",
        }
        if self.api_key:
            headers["X-ApiKey"] = self.api_key
        return headers

    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        Search Web of Science database
        """
        print(f"[WoS] Searching for: {query}")

        if not self.api_key:
            print("[WoS] API key required")
            return []

        try:
            params = {
                "databaseId": "WOS",
                "usrQuery": query,
                "count": min(max_results, 100),
                "firstRecord": 1,
            }

            response = self._make_request("", params=params)

            if not response or "Data" not in response:
                return []

            records = (
                response.get("Data", {})
                .get("Records", {})
                .get("records", {})
                .get("REC", [])
            )
            results = []

            for record in records:
                static_data = record.get("static_data", {})
                summary = static_data.get("summary", {})
                titles = summary.get("titles", {}).get("title", [])
                title = titles[0].get("content", "") if titles else ""

                result = {
                    "title": title,
                    "authors": [
                        name.get("full_name", "")
                        for name in summary.get("names", {}).get("name", [])
                    ],
                    "year": summary.get("pub_info", {}).get("@pubyear", ""),
                    "doi": static_data.get("fullrecord_metadata", {})
                    .get("references", {})
                    .get("reference", [{}])[0]
                    .get("doi", ""),
                    "abstract": "",
                    "source": "WoS",
                    "citations": record.get("dynamic_data", {})
                    .get("citation_related", {})
                    .get("tc_list", {})
                    .get("silo_tc", {})
                    .get("@local_count", 0),
                    "url": f"https://www.webofscience.com/wos/woscc/full-record/{record.get('UID', '')}",
                }
                results.append(result)

            return results

        except Exception as e:
            print(f"[WoS] Error during search: {e}")
            return []


class ScopusCrawler(BaseCrawler):
    """Scopus API Crawler

    API Documentation: https://dev.elsevier.com/technical_documentation.html
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.base_url = "https://api.elsevier.com/content/search/scopus"
        self.requests_per_second = 1

    def _get_headers(self) -> Dict[str, str]:
        """Override headers for Scopus API"""
        headers = {
            "Accept": "application/json",
            "User-Agent": "BibliometricCrawler/1.0",
        }
        if self.api_key:
            headers["X-ELS-APIKey"] = self.api_key
        return headers

    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        Search Scopus database using Elsevier API
        """
        print(f"[Scopus] Searching for: {query}")

        if not self.api_key:
            print("[Scopus] API key required")
            return []

        try:
            params = {
                "query": query,
                "count": min(max_results, 25),  # Max 25 per request
                "start": 0,
                "view": "COMPLETE",
            }

            response = self._make_request("", params=params)

            if not response or "search-results" not in response:
                return []

            entries = response.get("search-results", {}).get("entry", [])
            results = []

            for entry in entries:
                # Skip error entries
                if "error" in entry:
                    continue

                result = {
                    "title": entry.get("dc:title", ""),
                    "authors": [entry.get("dc:creator", "")],
                    "year": entry.get("prism:coverDate", "")[:4]
                    if entry.get("prism:coverDate")
                    else "",
                    "doi": entry.get("prism:doi", ""),
                    "abstract": entry.get("dc:description", ""),
                    "source": "Scopus",
                    "citations": int(entry.get("citedby-count", 0)),
                    "url": entry.get("prism:url", ""),
                    "journal": entry.get("prism:publicationName", ""),
                    "issn": entry.get("prism:issn", ""),
                    "scopus_id": entry.get("dc:identifier", "").replace(
                        "SCOPUS_ID:", ""
                    ),
                }
                results.append(result)

            return results

        except Exception as e:
            print(f"[Scopus] Error during search: {e}")
            return []


class ScienceDirectCrawler(BaseCrawler):
    """ScienceDirect API Crawler

    API Documentation: https://dev.elsevier.com/technical_documentation.html
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.base_url = "https://api.elsevier.com/content/search/sciencedirect"
        self.requests_per_second = 1

    def _get_headers(self) -> Dict[str, str]:
        """Override headers for ScienceDirect API"""
        headers = {
            "Accept": "application/json",
            "User-Agent": "BibliometricCrawler/1.0",
        }
        if self.api_key:
            headers["X-ELS-APIKey"] = self.api_key
        return headers

    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        Search ScienceDirect database using Elsevier API
        """
        print(f"[ScienceDirect] Searching for: {query}")

        if not self.api_key:
            print("[ScienceDirect] API key required")
            return []

        try:
            params = {
                "query": query,
                "count": min(max_results, 25),  # Max 25 per request
                "start": 0,
                "view": "COMPLETE",
            }

            response = self._make_request("", params=params)

            if not response or "search-results" not in response:
                return []

            entries = response.get("search-results", {}).get("entry", [])
            results = []

            for entry in entries:
                if "error" in entry:
                    continue

                result = {
                    "title": entry.get("dc:title", ""),
                    "authors": [entry.get("dc:creator", "")],
                    "year": entry.get("prism:coverDate", "")[:4]
                    if entry.get("prism:coverDate")
                    else "",
                    "doi": entry.get("prism:doi", ""),
                    "abstract": entry.get("dc:description", ""),
                    "source": "ScienceDirect",
                    "citations": 0,
                    "url": entry.get("prism:url", ""),
                    "journal": entry.get("prism:publicationName", ""),
                    "pii": entry.get("pii", ""),
                }
                results.append(result)

            return results

        except Exception as e:
            print(f"[ScienceDirect] Error during search: {e}")
            return []


class PubMedCrawler(BaseCrawler):
    """PubMed API Crawler

    API Documentation: https://www.ncbi.nlm.nih.gov/home/develop/api/
    """

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

    def __init__(self, api_key: Optional[str] = None):
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

    API Documentation: https://developer.ieee.org/docs/read/Searching_the_IEEE_Xplore_Metadata_API
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.base_url = "https://ieeexploreapi.ieee.org/api/v1/search/articles"
        self.requests_per_second = 1

    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        Search IEEE Xplore database
        """
        print(f"[IEEE] Searching for: {query}")

        if not self.api_key:
            print("[IEEE] API key required")
            return []

        try:
            params = {
                "querytext": query,
                "max_records": min(max_results, 200),
                "start_record": 1,
                "sort_order": "desc",
                "sort_field": "article_number",
                "apikey": self.api_key,
            }

            response = self._make_request("", params=params)

            if not response or "articles" not in response:
                return []

            articles = response.get("articles", [])
            results = []

            for article in articles:
                # Extract authors
                authors = []
                for author in article.get("authors", {}).get("authors", []):
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
    """Springer API Crawler

    API Documentation: https://dev.springernature.com/
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.base_url = "http://api.springernature.com/metadata/json"
        self.requests_per_second = 0.2  # ~5000 calls/day

    def _get_headers(self) -> Dict[str, str]:
        """Override headers for Springer API"""
        return {"Accept": "application/json", "User-Agent": "BibliometricCrawler/1.0"}

    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        Search Springer database
        """
        print(f"[Springer] Searching for: {query}")

        if not self.api_key:
            print("[Springer] API key required")
            return []

        try:
            params = {
                "q": query,
                "p": min(max_results, 100),  # Max 100 per request
                "api_key": self.api_key,
            }

            response = self._make_request("", params=params)

            if not response or "records" not in response:
                return []

            records = response.get("records", [])
            results = []

            for record in records:
                result = {
                    "title": record.get("title", ""),
                    "authors": [
                        creator.get("creator", "")
                        for creator in record.get("creators", [])
                    ],
                    "year": record.get("publicationDate", "")[:4]
                    if record.get("publicationDate")
                    else "",
                    "doi": record.get("doi", ""),
                    "abstract": record.get("abstract", ""),
                    "source": "Springer",
                    "citations": 0,
                    "url": record.get("url", [{}])[0].get("value", ""),
                    "journal": record.get("publicationName", ""),
                    "issn": record.get("issn", ""),
                }
                results.append(result)

            return results

        except Exception as e:
            print(f"[Springer] Error during search: {e}")
            return []


class EBSCOCrawler(BaseCrawler):
    """EBSCO API Crawler

    API Documentation: https://connect.ebsco.com/s/article/EBSCOhost-API-Making-Requests-with-REST
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.base_url = "https://api.ebsco.io/"
        self.auth_token = None

    def _authenticate(self) -> bool:
        """EBSCO requires OAuth authentication"""
        if not self.api_key:
            return False

        try:
            # EBSCO uses complex OAuth flow
            # This is a simplified placeholder - actual implementation needs OAuth flow
            print("[EBSCO] Authentication required - OAuth flow needed")
            return False
        except Exception as e:
            print(f"[EBSCO] Authentication error: {e}")
            return False

    def search(self, query: str, max_results: int = 100) -> List[Dict[str, Any]]:
        """
        Search EBSCO database
        Note: EBSCO requires complex OAuth authentication
        """
        print(f"[EBSCO] Searching for: {query}")
        print(
            "[EBSCO] Note: Full implementation requires OAuth 2.0 authentication flow"
        )

        if not self._authenticate():
            print("[EBSCO] Authentication required - skipping")
            return []

        # Placeholder for actual search after authentication
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
