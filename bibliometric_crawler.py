"""
Main bibliometric data crawler script with Groq AI integration.
Handles user queries, data retrieval, and AI-powered data filtering.
"""

import json
import os
import re
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from groq import Groq

try:
    from cerebras.cloud.sdk import Cerebras

    CEREBRAS_AVAILABLE = True
except Exception:
    Cerebras = None
    CEREBRAS_AVAILABLE = False

from crawlers import (
    EBSCOCrawler,
    ERICCrawler,
    GeneCrawler,
    GenomeCrawler,
    IEEECrawler,
    PubChemCrawler,
    PubMedCrawler,
    SAGECrawler,
    ScienceDirectCrawler,
    ScopusCrawler,
    SpringerCrawler,
    WileyCrawler,
    WoSCrawler,
)

# Load environment variables
load_dotenv()


class BibliometricCrawler:
    """Main orchestrator for bibliometric data crawling"""

    def __init__(self, groq_model: str = None, cache_dir: str = ".cache", cache_ttl: int = 3600, max_workers: int = 8):
        """Initialize the crawler with API keys and crawlers

        Args:
            groq_model: The Groq AI model to use (default: from env or llama-3.1-70b-versatile)
            cache_dir: directory to store integration/validation caches
            cache_ttl: time-to-live (seconds) for cached validation results
            max_workers: default number of threads for parallel operations
        """
        groq_api_key = os.getenv("GROQ_API_KEY")
        if not groq_api_key:
            raise ValueError(
                "GROQ_API_KEY not found in environment variables. "
                "Please set your Groq API key in the .env file or environment."
            )

        self.groq_client = Groq(api_key=groq_api_key)
        self.groq_model = groq_model or os.getenv(
            "GROQ_MODEL", "llama-3.1-70b-versatile"
        )

        # Integration configuration
        self.cache_dir = cache_dir
        self.cache_ttl = cache_ttl
        self.max_workers = max_workers

        # Initialize all crawlers
        # Support shared API keys: NCBI (PubMed/PubChem/Gene/Genome) and Elsevier (Scopus/ScienceDirect)
        pubmed_key = os.getenv("PUBMED_API_KEY")
        elsevier_key = os.getenv("SCOPUS_API_KEY") or os.getenv("SCIENCEDIRECT_API_KEY")
        shared_ncbi_key = pubmed_key or os.getenv("PUBCHEM_API_KEY") or os.getenv("GENE_API_KEY") or os.getenv("GENOME_API_KEY")

        self.crawlers = {
            "wos": WoSCrawler(os.getenv("WOS_API_KEY")),
            "scopus": ScopusCrawler(elsevier_key),
            "sciencedirect": ScienceDirectCrawler(elsevier_key),
            "pubmed": PubMedCrawler(shared_ncbi_key or pubmed_key),
            "pubchem": PubChemCrawler(shared_ncbi_key),
            "gene": GeneCrawler(shared_ncbi_key),
            "genome": GenomeCrawler(shared_ncbi_key),
            "sage": SAGECrawler(os.getenv("SAGE_API_KEY")),
            "ieee": IEEECrawler(os.getenv("IEEE_API_KEY")),
            "eric": ERICCrawler(os.getenv("ERIC_API_KEY")),
            "springer": SpringerCrawler(os.getenv("SPRINGER_API_KEY")),
            "ebsco": EBSCOCrawler(os.getenv("EBSCO_API_KEY")),
            "wiley": WileyCrawler(os.getenv("WILEY_API_KEY")),
        }

        # Registry for optional provider token-scope probes. Attach callables that accept (crawler) and return dict of scopes/info.
        # Example: self.register_scope_probe('scopus', lambda c: {'scopes': ['search']})
        self.scope_probes = {}

    def register_scope_probe(self, provider_name: str, probe_callable) -> None:
        """Register a callable to probe a provider for token scope or metadata.

        The callable receives the crawler instance and should return a dict (e.g., {'scopes': [...]}) or None.
        """
        self.scope_probes[provider_name] = probe_callable

    def check_api_keys(self) -> Dict[str, Dict[str, object]]:
        """Return a dict describing which crawler API keys are present in the current environment.

        The returned mapping has the shape:
            { crawler_name: {"env": ENV_VAR_NAME, "present": bool, "value": str|None } }
        """
        mapping = {
            "wos": "WOS_API_KEY",
            "scopus": "SCOPUS_API_KEY",
            "sciencedirect": "SCIENCEDIRECT_API_KEY",
            "pubmed": "PUBMED_API_KEY",
            "pubchem": "PUBCHEM_API_KEY",
            "gene": "GENE_API_KEY",
            "genome": "GENOME_API_KEY",
            "sage": "SAGE_API_KEY",
            "ieee": "IEEE_API_KEY",
            "eric": "ERIC_API_KEY",
            "springer": "SPRINGER_API_KEY",
            "ebsco": "EBSCO_API_KEY",
            "wiley": "WILEY_API_KEY",
        }
        result: Dict[str, Dict[str, object]] = {}
        for name, env_var in mapping.items():
            val = os.getenv(env_var)
            result[name] = {"env": env_var, "present": bool(val), "value": val}
        return result

    def get_missing_api_keys(self) -> Dict[str, str]:
        """Return a mapping of crawler_name -> env_var for missing keys."""
        missing = {name: info["env"] for name, info in self.check_api_keys().items() if not info["present"]}
        return missing

    def get_effective_api_keys(self) -> Dict[str, Optional[str]]:
        """Return the effective API key string in use by each crawler instance (after shared-key fallback)."""
        return {name: (crawler.api_key if crawler.api_key else None) for name, crawler in self.crawlers.items()}

    def _cache_path(self) -> str:
        import os
        return os.path.join(self.cache_dir, "validation_cache.json")

    def _load_validation_cache(self) -> Dict[str, object]:
        import os
        import json
        import time
        path = self._cache_path()
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                cached = json.load(fh)
            # expire by timestamp
            ts = cached.get("timestamp", 0)
            if time.time() - ts > self.cache_ttl:
                return {}
            return cached.get("results", {})
        except Exception:
            return {}

    def _save_validation_cache(self, results: Dict[str, object]) -> None:
        import os
        import json
        import time
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(self._cache_path(), "w", encoding="utf-8") as fh:
                json.dump({"timestamp": int(time.time()), "results": results}, fh)
        except Exception:
            # swallow cache errors (non-critical)
            pass

    def validate_keys(self, timeout: int = 10, invalidate_cache: bool = False, parallel: bool = True) -> Dict[str, Dict[str, object]]:
        """Validate API keys by performing a lightweight probe for each configured crawler.

        Features:
        - Caches results to disk (TTL controlled by `cache_ttl`)
        - Can invalidate cache with `invalidate_cache=True`
        - Runs probes in parallel using ThreadPoolExecutor when `parallel=True`

        Returns a mapping: { crawler_name: {"ok": bool, "status": int|None, "message": str } }
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        if not invalidate_cache:
            cached = self._load_validation_cache()
            if cached:
                return cached

        results: Dict[str, Dict[str, object]] = {}

        def _probe(name, crawler):
            info = {"ok": None, "status": None, "message": ""}
            try:
                probe_resp = None
                try:
                    if hasattr(crawler, "search"):
                        _ = crawler.search("test", max_results=1)
                        probe_resp = True
                    else:
                        probe_resp = crawler._make_request("", params={}, method="GET")
                except Exception as probe_exc:
                    try:
                        from requests.exceptions import HTTPError

                        if isinstance(probe_exc, HTTPError) and getattr(probe_exc, "response", None):
                            info["status"] = getattr(probe_exc.response, "status_code", None)
                            info["message"] = getattr(probe_exc.response, "text", str(probe_exc))
                        else:
                            info["message"] = str(probe_exc)
                    except Exception:
                        info["message"] = str(probe_exc)
                    info["ok"] = False
                    return name, info

                if probe_resp:
                    info["ok"] = True
                    info["message"] = "OK"
                    # Optionally run a registered scope probe for more information
                    sp = self.scope_probes.get(name)
                    if sp:
                        try:
                            info["scopes"] = sp(crawler) or {}
                        except Exception as es:
                            info["scopes"] = {"error": str(es)}
                else:
                    info["ok"] = False
                    info["message"] = "Empty response from probe"

            except Exception as e:
                info["ok"] = False
                info["message"] = str(e)

            return name, info

        if parallel:
            with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
                futures = {ex.submit(_probe, name, crawler): name for name, crawler in self.crawlers.items()}
                for fut in as_completed(futures):
                    name, info = fut.result()
                    results[name] = info
        else:
            for name, crawler in self.crawlers.items():
                name, info = _probe(name, crawler)
                results[name] = info

        # save cache
        self._save_validation_cache(results)

        return results

    def _select_and_set_fallback_groq_model(self) -> Optional[str]:
        """
        Attempt to select a fallback Groq model by listing available models and
        heuristically scoring them. If a candidate is found, set `self.groq_model`
        to the selected model id and return it. On failure return None.
        """
        try:
            models_resp = self.groq_client.models.list()
            models_list = getattr(models_resp, "data", None) or []
            best_model = None
            best_score = -1
            for m in models_list:
                # m can be a pydantic model or dict-like
                model_id = None
                try:
                    model_id = getattr(m, "id", None)
                except Exception:
                    model_id = None
                if not model_id and isinstance(m, dict):
                    model_id = m.get("id")
                if not model_id:
                    try:
                        model_id = str(m)
                    except Exception:
                        continue
                mid = str(model_id)
                key = mid.lower()

                score = 0
                # Prefer models with 'versatile' in the name
                if "versatile" in key:
                    score += 100
                # Small boost for 'chat' or conversational models
                if "chat" in key or "conversational" in key:
                    score += 20
                # Prefer larger 'b' sizes (e.g., 70b > 13b)
                m_match = re.search(r"(\d+)\s*[bB]", mid)
                if m_match:
                    try:
                        score += int(m_match.group(1))
                    except Exception:
                        pass

                if score > best_score:
                    best_score = score
                    best_model = mid

            if best_model:
                self.groq_model = best_model
                print(f"[Groq] Selected fallback model: {best_model}")
                return best_model
            return None
        except Exception as ex:
            print(f"[Groq] Failed to select fallback model: {ex}")
            return None

    def analyze_user_query(self, user_query: str) -> Dict[str, Any]:
        """
        Use Groq AI to analyze the user's query and determine search parameters.
        This method will attempt an automatic fallback to another Groq model if the
        configured model is decommissioned.
        """
        system_prompt = """You are a bibliometric research assistant. Analyze the user's query and extract:
    1. The main research topic or keywords
    2. Potential search variations (e.g., "data mining" and "data-mining")
    3. Relevant academic databases to search
    4. Any specific filters or constraints

    Return your analysis as a JSON object with these keys:
    - search_terms: list of search terms and variations
    - databases: list of relevant databases (use: wos, scopus, sciencedirect, pubmed, pubchem, gene, genome, sage, ieee, eric, springer, ebsco, wiley)
    - filters: any date ranges, publication types, or other filters
    - normalized_query: a standardized version of the query for searching"""

        def _call_chat_model(model_name: str):
            return self.groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query},
                ],
                model=model_name,
                temperature=0.3,
                max_tokens=1000,
            )

        last_exc = None
        try:
            response = _call_chat_model(self.groq_model)
            analysis_text = response.choices[0].message.content

            # Try to extract JSON from the response
            try:
                # JSON may be wrapped in markdown code fences
                if "```json" in analysis_text:
                    json_start = analysis_text.find("```json") + 7
                    json_end = analysis_text.find("```", json_start)
                    analysis_text = analysis_text[json_start:json_end]
                elif "```" in analysis_text:
                    json_start = analysis_text.find("```") + 3
                    json_end = analysis_text.find("```", json_start)
                    analysis_text = analysis_text[json_start:json_end]

                analysis = json.loads(analysis_text.strip())
                # Record provider metadata
                analysis["_ai_provider"] = {"provider": "groq", "model": self.groq_model}
            except json.JSONDecodeError as je:
                # Do not fall back to non-AI behavior; raise an explicit error
                raise RuntimeError(f"Groq returned non-JSON analysis: {je}") from je

            return analysis

        except Exception as e:
            # Record last exception for debugging/reporting
            last_exc = e
            err_str = str(e)

            # If the error indicates a decommissioned Groq model, attempt to select and use a fallback Groq model
            if "model_decommissioned" in err_str or "decommissioned" in err_str:
                try:
                    fallback_model = self._select_and_set_fallback_groq_model()
                except Exception as ex:
                    print(f"[Groq] Error while selecting fallback model: {ex}")
                else:
                    if fallback_model:
                        try:
                            response = _call_chat_model(self.groq_model)
                            analysis_text = response.choices[0].message.content

                            # Try to extract JSON from the response
                            if "```json" in analysis_text:
                                json_start = analysis_text.find("```json") + 7
                                json_end = analysis_text.find("```", json_start)
                                analysis_text = analysis_text[json_start:json_end]
                            elif "```" in analysis_text:
                                json_start = analysis_text.find("```") + 3
                                json_end = analysis_text.find("```", json_start)
                                analysis_text = analysis_text[json_start:json_end]

                            analysis = json.loads(analysis_text.strip())
                            analysis["_ai_provider"] = {"provider": "groq", "model": self.groq_model}
                            return analysis
                        except json.JSONDecodeError as je:
                            # Do not fall back to non-AI behavior; raise an explicit error
                            raise RuntimeError(f"Groq fallback returned non-JSON analysis: {je}") from je
                        except Exception as e2:
                            print(f"[Groq] Retry with fallback model {self.groq_model} failed: {e2}")

            # Try Cloudflare AI as an AI-only fallback (preferred over other third-party fallbacks)
            cf_endpoint = os.getenv("CLOUDFLARE_AI_ENDPOINT")
            cf_token = os.getenv("CLOUDFLARE_API_TOKEN")
            if cf_endpoint and cf_token:
                try:
                    import requests

                    headers = {"Authorization": f"Bearer {cf_token}", "Content-Type": "application/json"}
                    payload = {"messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_query}], "model": os.getenv("CLOUDFLARE_MODEL", "gpt-4o")}
                    r = requests.post(cf_endpoint, headers=headers, json=payload, timeout=30)
                    r.raise_for_status()
                    resp_json = r.json()
                    cf_text = None
                    try:
                        cf_text = resp_json.get("choices", [])[0].get("message", {}).get("content")
                    except Exception:
                        cf_text = resp_json.get("text") or str(resp_json)
                    if cf_text:
                        if "```json" in cf_text:
                            json_start = cf_text.find("```json") + 7
                            json_end = cf_text.find("```", json_start)
                            cf_text = cf_text[json_start:json_end]
                        elif "```" in cf_text:
                            json_start = cf_text.find("```") + 3
                            json_end = cf_text.find("```", json_start)
                            cf_text = cf_text[json_start:json_end]
                        analysis = json.loads(cf_text.strip())
                        analysis["_ai_provider"] = {"provider": "cloudflare", "model": os.getenv("CLOUDFLARE_MODEL", "gpt-4o")}
                        return analysis
                except Exception as ecf:
                    print(f"[Cloudflare AI] Fallback failed: {ecf}")

            # Attempt Cerebras fallback if available and the user has provided a key
            if CEREBRAS_AVAILABLE and os.getenv("CEREBRAS_API_KEY"):
                try:
                    cb_model = os.getenv("CEREBRAS_MODEL", "llama-3.3-70b")
                    cb_client = Cerebras(api_key=os.getenv("CEREBRAS_API_KEY"))
                    cb_response = cb_client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_query},
                        ],
                        model=cb_model,
                        temperature=0.3,
                        max_tokens=1000,
                    )
                    # Extract content from Cerebras response (robust extraction)
                    cb_text = None
                    try:
                        cb_text = cb_response.choices[0].message.content
                    except Exception:
                        try:
                            cb_text = (
                                cb_response.get("choices", [])[0]
                                .get("message", {})
                                .get("content", "")
                            )
                        except Exception:
                            cb_text = str(cb_response)
                    if cb_text:
                        # Try to parse JSON embedded in code block (same parsing as for Groq)
                        analysis_text = cb_text
                        try:
                            if "```json" in analysis_text:
                                json_start = analysis_text.find("```json") + 7
                                json_end = analysis_text.find("```", json_start)
                                analysis_text = analysis_text[json_start:json_end]
                            elif "```" in analysis_text:
                                json_start = analysis_text.find("```") + 3
                                json_end = analysis_text.find("```", json_start)
                                analysis_text = analysis_text[json_start:json_end]
                            analysis = json.loads(analysis_text.strip())
                            analysis["_ai_provider"] = {"provider": "cerebras", "model": cb_model}
                            return analysis
                        except Exception as ecb_inner:
                            print(f"[Cerebras] parsing failed: {ecb_inner}")
                            last_exc = ecb_inner
                except Exception as ecb:
                    print(f"[Cerebras] Fallback failed: {ecb}")

            # No non-AI fallback allowed — raise an explicit error indicating AI failure
            raise RuntimeError(f"AI providers failed to produce analysis: {last_exc}") from last_exc

    def crawl_databases(
        self, analysis: Dict[str, Any], max_results: int = 100
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Crawl the selected databases based on the analysis
        """
        results = {}
        search_terms = analysis.get(
            "search_terms", [analysis.get("normalized_query", "")]
        )
        databases = analysis.get("databases", list(self.crawlers.keys()))

        print(f"\nCrawling {len(databases)} databases for: {search_terms}")
        print("=" * 60)

        # Optionally perform searches concurrently across databases and term variations
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Helper function to run a single search and return (db_name, results)
        def _search_one(db_name, crawler, term):
            try:
                return db_name, crawler.search(term, max_results)
            except Exception as e:
                print(f"Error crawling {db_name} for '{term}': {e}")
                return db_name, []

        # Use ThreadPoolExecutor to parallelize IO-bound search operations
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futures = []
            for db_name in databases:
                if db_name in self.crawlers:
                    crawler = self.crawlers[db_name]
                    for term in search_terms:
                        futures.append(ex.submit(_search_one, db_name, crawler, term))

            # Collect as they complete
            interim: Dict[str, List[Dict[str, Any]]] = {db_name: [] for db_name in databases}
            for fut in as_completed(futures):
                db_name, term_results = fut.result()
                if db_name in interim:
                    interim[db_name].extend(term_results)

        # Assign results for dbs we searched
        for db_name in databases:
            if db_name in interim:
                results[db_name] = interim.get(db_name, [])

        return results

    def filter_and_normalize_results(
        self, raw_results: Dict[str, List[Dict[str, Any]]], user_query: str
    ) -> Dict[str, Any]:
        """
        Use Groq AI to filter and normalize results, combining similar entries
        """
        # Prepare a summary of results for AI processing
        result_summary = {}
        total_results = 0

        for db_name, results in raw_results.items():
            result_summary[db_name] = len(results)
            total_results += len(results)

        print(f"\n\nProcessing {total_results} total results with Groq AI...")
        print("=" * 60)

        filter_prompt = f"""Given bibliometric search results for the query: "{user_query}"

Task: Analyze and provide guidance on filtering and normalizing these results:
1. Identify potential duplicate entries (e.g., "data mining" vs "data-mining")
2. Suggest normalization rules for combining similar terms
3. Recommend how to deduplicate results across databases
4. Provide a strategy for ranking/filtering the most relevant results

Result counts by database:
{json.dumps(result_summary, indent=2)}

Provide your analysis as a JSON object with:
- normalization_rules: dict mapping variations to canonical forms
- deduplication_strategy: description of how to identify duplicates
- relevance_criteria: list of criteria for ranking results
- recommended_filters: any filters to apply"""

        try:
            last_exc = None
            response = self.groq_client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a bibliometric data analyst. Provide structured guidance for data normalization and filtering.",
                    },
                    {"role": "user", "content": filter_prompt},
                ],
                model=self.groq_model,
                temperature=0.3,
                max_tokens=1500,
            )

            filtering_guidance = response.choices[0].message.content
            print("\nAI Filtering Guidance:")
            print(filtering_guidance)

            # Try to extract JSON guidance
            try:
                if "```json" in filtering_guidance:
                    json_start = filtering_guidance.find("```json") + 7
                    json_end = filtering_guidance.find("```", json_start)
                    filtering_guidance = filtering_guidance[json_start:json_end]
                elif "```" in filtering_guidance:
                    json_start = filtering_guidance.find("```") + 3
                    json_end = filtering_guidance.find("```", json_start)
                    filtering_guidance = filtering_guidance[json_start:json_end]

                guidance = json.loads(filtering_guidance.strip())
                filtering_provider = {"provider": "groq", "model": self.groq_model}
            except json.JSONDecodeError as je:
                raise RuntimeError(f"Groq returned non-JSON filtering guidance: {je}") from je

        except Exception as e:
            err_str = str(e)
            # If the model has been decommissioned, attempt to pick an alternative and retry
            if "model_decommissioned" in err_str or "decommissioned" in err_str:
                print(
                    "Error getting filtering guidance: the Groq model appears to be decommissioned. "
                    "Attempting automatic model selection and retry..."
                )
                fallback_model = None
                try:
                    fallback_model = self._select_and_set_fallback_groq_model()
                except Exception as sel_ex:
                    print(f"[Groq] Fallback selection failed: {sel_ex}")

                if fallback_model:
                    try:
                        response = self.groq_client.chat.completions.create(
                            messages=[
                                {
                                    "role": "system",
                                    "content": "You are a bibliometric data analyst. Provide structured guidance for data normalization and filtering.",
                                },
                                {"role": "user", "content": filter_prompt},
                            ],
                            model=self.groq_model,
                            temperature=0.3,
                            max_tokens=1500,
                        )

                        filtering_guidance = response.choices[0].message.content
                        print("\nAI Filtering Guidance:")
                        print(filtering_guidance)

                        # Try to extract JSON guidance
                        try:
                            if "```json" in filtering_guidance:
                                json_start = filtering_guidance.find("```json") + 7
                                json_end = filtering_guidance.find("```", json_start)
                                filtering_guidance = filtering_guidance[
                                    json_start:json_end
                                ]
                            elif "```" in filtering_guidance:
                                json_start = filtering_guidance.find("```") + 3
                                json_end = filtering_guidance.find("```", json_start)
                                filtering_guidance = filtering_guidance[
                                    json_start:json_end
                                ]

                            guidance = json.loads(filtering_guidance.strip())
                        except json.JSONDecodeError as je:
                            raise RuntimeError(f"Groq fallback returned non-JSON filtering guidance: {je}") from je
                    except Exception as e2:
                        print(
                            f"[Groq] Retry with fallback model {self.groq_model} failed: {e2}"
                        )
                        last_exc = e2
                        guidance = None
                else:
                    print(
                        "[Groq] No fallback model could be selected; attempting Cerebras fallback..."
                    )
                    guidance = None
                    # Try Cerebras as a provider fallback if available
                    if CEREBRAS_AVAILABLE and os.getenv("CEREBRAS_API_KEY"):
                        try:
                            cb_client = Cerebras(api_key=os.getenv("CEREBRAS_API_KEY"))
                            cb_model = os.getenv("CEREBRAS_MODEL", "llama-3.3-70b")
                            cb_resp = cb_client.chat.completions.create(
                                messages=[
                                    {
                                        "role": "system",
                                        "content": "You are a bibliometric data analyst. Provide structured guidance for data normalization and filtering.",
                                    },
                                    {"role": "user", "content": filter_prompt},
                                ],
                                model=cb_model,
                                temperature=0.3,
                                max_tokens=1500,
                            )
                            # Extract guidance text robustly
                            cb_text = None
                            try:
                                cb_text = cb_resp.choices[0].message.content
                            except Exception:
                                try:
                                    cb_text = (
                                        cb_resp.get("choices", [])[0]
                                        .get("message", {})
                                        .get("content", "")
                                    )
                                except Exception:
                                    cb_text = str(cb_resp)
                            if cb_text:
                                print("\nAI Filtering Guidance (Cerebras):")
                                print(cb_text)
                                try:
                                    if "```json" in cb_text:
                                        json_start = cb_text.find("```json") + 7
                                        json_end = cb_text.find("```", json_start)
                                        cb_text = cb_text[json_start:json_end]
                                    elif "```" in cb_text:
                                        json_start = cb_text.find("```") + 3
                                        json_end = cb_text.find("```", json_start)
                                        cb_text = cb_text[json_start:json_end]
                                    guidance = json.loads(cb_text.strip())
                                    filtering_provider = {"provider": "cerebras", "model": cb_model}
                                except Exception as ecb_inner:
                                    print(f"[Cerebras] parsing failed: {ecb_inner}")
                                    last_exc = ecb_inner
                                    guidance = None
                        except Exception as ecb:
                            print(f"[Cerebras] fallback failed: {ecb}")
                    if guidance is None:
                        # continue to attempt other AI-only fallbacks
                        pass

            # If we reached here and guidance was produced by an AI fallback (Cerebras/Cloudflare), attach provider info
            # Note: guidance_provider may have been set by subsequent fallbacks below
            else:
                print(f"Error getting filtering guidance: {e}")
                last_exc = e
                # Attempt Cloudflare fallback if configured
                cf_endpoint = os.getenv("CLOUDFLARE_AI_ENDPOINT")
                cf_token = os.getenv("CLOUDFLARE_API_TOKEN")
                if cf_endpoint and cf_token:
                    try:
                        import requests

                        headers = {"Authorization": f"Bearer {cf_token}", "Content-Type": "application/json"}
                        payload = {"messages": [{"role": "system", "content": "You are a bibliometric data analyst. Provide structured guidance for data normalization and filtering."}, {"role": "user", "content": filter_prompt}], "model": os.getenv("CLOUDFLARE_MODEL", "gpt-4o")}
                        r = requests.post(cf_endpoint, headers=headers, json=payload, timeout=30)
                        r.raise_for_status()
                        resp_json = r.json()
                        cf_text = None
                        try:
                            cf_text = resp_json.get("choices", [])[0].get("message", {}).get("content")
                        except Exception:
                            cf_text = resp_json.get("text") or str(resp_json)
                        if cf_text:
                            if "```json" in cf_text:
                                json_start = cf_text.find("```json") + 7
                                json_end = cf_text.find("```", json_start)
                                cf_text = cf_text[json_start:json_end]
                            elif "```" in cf_text:
                                json_start = cf_text.find("```") + 3
                                json_end = cf_text.find("```", json_start)
                                cf_text = cf_text[json_start:json_end]
                            guidance = json.loads(cf_text.strip())
                            filtering_provider = {"provider": "cloudflare", "model": os.getenv("CLOUDFLARE_MODEL", "gpt-4o")}
                        else:
                            guidance = None
                    except Exception as ecf:
                        print(f"[Cloudflare AI] Fallback failed: {ecf}")
                        last_exc = ecf
                else:
                    guidance = None

        # If guidance could not be produced by any AI provider, raise an error
        if guidance is None:
            raise RuntimeError(f"AI providers failed to produce filtering guidance: {last_exc}") from last_exc

        # Return both raw results and filtering guidance
        return {
            "raw_results": raw_results,
            "result_summary": result_summary,
            "total_results": total_results,
            "filtering_guidance": guidance,
            "filtering_provider": (filtering_provider if 'filtering_provider' in locals() else None),
            "user_query": user_query,
        }

    def process_query(self, user_query: str, max_results: int = 100) -> Dict[str, Any]:
        """
        Main entry point: process a user query end-to-end
        """
        print(f"\n{'=' * 60}")
        print(f"Processing query: {user_query}")
        print(f"{'=' * 60}\n")

        # Step 1: Analyze query with AI
        print("Step 1: Analyzing query with Groq AI...")
        analysis = self.analyze_user_query(user_query)
        print("Analysis complete:")
        print(f"  - Search terms: {analysis.get('search_terms', [])}")
        print(f"  - Databases: {analysis.get('databases', [])}")
        print(f"  - Normalized query: {analysis.get('normalized_query', '')}")

        # Step 2: Crawl databases
        print("\nStep 2: Crawling academic databases...")
        raw_results = self.crawl_databases(analysis, max_results)

        # Step 3: Filter and normalize with AI
        print("\nStep 3: Filtering and normalizing results with AI...")
        processed_results = self.filter_and_normalize_results(raw_results, user_query)

        # Attach analysis provider metadata so callers can display traceability
        processed_results["analysis"] = analysis
        processed_results["analysis_provider"] = analysis.get("_ai_provider")
        processed_results["filtering_provider"] = processed_results.get("filtering_provider")

        return processed_results


def main():
    """Main function for CLI usage"""
    print("Bibliometric Data Crawler with Groq AI")
    print("=" * 60)

    # Check for API key
    if not os.getenv("GROQ_API_KEY"):
        print("ERROR: GROQ_API_KEY not found in environment variables.")
        print("Please create a .env file with your API keys.")
        print("See .env.example for reference.")
        return

    # Initialize crawler
    try:
        crawler = BibliometricCrawler()
    except ValueError as e:
        print(f"ERROR: {e}")
        return

    # Get user query
    # Support quick validation flag for CI/diagnostics: `--validate-keys`
    import sys
    # Validate keys CLI support: --validate-keys [--invalidate-cache] [--max-workers N]
    if "--validate-keys" in sys.argv:
        invalidate = "--invalidate-cache" in sys.argv
        # optional max workers override
        maxw = None
        if "--max-workers" in sys.argv:
            try:
                idx = sys.argv.index("--max-workers")
                maxw = int(sys.argv[idx + 1])
                crawler.max_workers = maxw
            except Exception:
                pass

        print("Validating configured API keys (this may perform small probe requests)...")
        v = crawler.validate_keys(invalidate_cache=invalidate)
        print("\nKey validation results:")
        for k, info in v.items():
            status = "OK" if info.get("ok") else f"INVALID (status={info.get('status')})"
            msg = info.get("message", "")
            print(f" - {k}: {status} - {msg}")
        return

    print("\nEnter your research query (or 'quit' to exit):")
    while True:
        user_query = input("\n> ").strip()

        if user_query.lower() in ["quit", "exit", "q"]:
            print("Goodbye!")
            break

        if not user_query:
            continue

        # Process the query
        try:
            results = crawler.process_query(user_query)

            print("\n" + "=" * 60)
            print("RESULTS SUMMARY")
            print("=" * 60)
            print(json.dumps(results["result_summary"], indent=2))
            print(f"\nTotal results found: {results['total_results']}")

        except Exception as e:
            print(f"Error processing query: {e}")
            import traceback

            traceback.print_exc()


if __name__ == "__main__":
    main()
