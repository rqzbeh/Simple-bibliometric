import pytest
from bibliometric_crawler import BibliometricCrawler


def test_register_scope_probe(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    bc = BibliometricCrawler()

    called = {"scopus": 0}

    def probe(crawler):
        called["scopus"] += 1
        return {"scopes": ["search"]}

    bc.register_scope_probe("scopus", probe)

    # Make scopus probe successful
    def ok_search(q, max_results=1):
        return [{"title": "ok"}]

    monkeypatch.setattr(bc.crawlers["scopus"], "search", ok_search)

    res = bc.validate_keys(invalidate_cache=True)
    assert res["scopus"]["ok"] is True
    assert "scopes" in res["scopus"]
    assert called["scopus"] == 1
