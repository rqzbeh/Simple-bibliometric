import pytest
from requests.exceptions import HTTPError

from bibliometric_crawler import BibliometricCrawler


def test_validate_keys_detects_invalid_wos(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    # create crawler
    bc = BibliometricCrawler()

    # Create a fake HTTPError with response
    class FakeResp:
        status_code = 401
        text = '{"message":"Invalid authentication credentials"}'

    http_err = HTTPError("401 Client Error")
    http_err.response = FakeResp()

    def raise_http(*args, **kwargs):
        raise http_err

    monkeypatch.setattr(bc.crawlers["wos"], "search", raise_http)

    results = bc.validate_keys(invalidate_cache=True)

    assert results["wos"]["ok"] is False
    assert results["wos"]["status"] == 401
    assert "Invalid authentication credentials" in results["wos"]["message"]


def test_validate_keys_detects_ok(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    # create crawler
    bc = BibliometricCrawler()

    def ok_search(q, max_results=1):
        return [{"title": "dummy"}]

    monkeypatch.setattr(bc.crawlers["scopus"], "search", ok_search)

    results = bc.validate_keys(invalidate_cache=True)

    assert results["scopus"]["ok"] is True
    assert results["scopus"]["message"] == "OK"
