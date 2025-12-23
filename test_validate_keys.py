from bibliometric_crawler import BibliometricCrawler


class FakeCrawler:
    env_var = "FAKE_API_KEY"

    def __init__(self, api_key=None):
        self.api_key = api_key

    def search(self, query, max_results=1):
        # Simulate an auth failure where search returns empty list
        return []


def test_validate_keys_detects_empty_search_as_failure(tmp_path, monkeypatch):
    bc = BibliometricCrawler()
    # Inject fake crawler
    bc.crawlers["fake"] = FakeCrawler(api_key="dummy")

    res = bc.validate_keys(invalidate_cache=True, parallel=False)
    assert "fake" in res
    assert res["fake"]["ok"] is False
    assert "Empty response" in res["fake"]["message"]
