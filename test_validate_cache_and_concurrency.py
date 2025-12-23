import time
import pytest

from bibliometric_crawler import BibliometricCrawler


def test_validate_keys_uses_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")

    called = {"wos": 0}

    def fake_search(q, max_results=1):
        called["wos"] += 1
        return [{"title": "ok"}]

    bc = BibliometricCrawler(cache_dir=str(tmp_path), cache_ttl=60)
    monkeypatch.setattr(bc.crawlers["wos"], "search", fake_search)

    # first call should invoke search
    res1 = bc.validate_keys()
    assert res1["wos"]["ok"] is True
    assert called["wos"] == 1

    # Replace search with a function that would fail if called
    def fail_search(q, max_results=1):
        raise RuntimeError("should not be called when using cache")

    monkeypatch.setattr(bc.crawlers["wos"], "search", fail_search)

    # second call should use cache and not call search
    res2 = bc.validate_keys()
    assert res2["wos"]["ok"] is True
    assert called["wos"] == 1


def test_crawl_databases_concurrent(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")

    bc = BibliometricCrawler(max_workers=4)

    # Mock pubmed and scopus search to return identifiable data
    def pubmed_search(q, max_results=100):
        return [{"title": f"pm:{q}"}]

    def scopus_search(q, max_results=100):
        return [{"title": f"sc:{q}"}]

    monkeypatch.setattr(bc.crawlers["pubmed"], "search", pubmed_search)
    monkeypatch.setattr(bc.crawlers["scopus"], "search", scopus_search)

    analysis = {"search_terms": ["a", "b"], "databases": ["pubmed", "scopus"]}

    results = bc.crawl_databases(analysis, max_results=5)

    assert "pubmed" in results and "scopus" in results
    assert any(r["title"].startswith("pm:") for r in results["pubmed"]) 
    assert any(r["title"].startswith("sc:") for r in results["scopus"])