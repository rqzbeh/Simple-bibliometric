from bibliometric_crawler import BibliometricCrawler


class FakeHTTPErrorCrawler:
    env_var = "FAKE_API_KEY"

    def __init__(self, api_key=None):
        self.api_key = api_key

    def _make_request(self, endpoint, params=None, method="GET"):
        # Simulate a 401 response captured by _make_request
        return {"error": {"status": 401, "text": "Invalid API key"}}


def test_validate_keys_includes_http_error_details(tmp_path, monkeypatch):
    bc = BibliometricCrawler()
    # Inject fake crawler that returns an error dict from _make_request
    bc.crawlers["fake_http"] = FakeHTTPErrorCrawler(api_key="dummy")

    res = bc.validate_keys(invalidate_cache=True, parallel=False)
    assert "fake_http" in res
    info = res["fake_http"]
    assert info["ok"] is False
    assert info["status"] == 401
    assert "Invalid API key" in info["message"]
