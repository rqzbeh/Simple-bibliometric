import pytest

from bibliometric_crawler import BibliometricCrawler


class DummyChat:
    class Comp:
        def create(self, *args, **kwargs):
            raise Exception("simulated groq failure")


class DummyClient:
    def __init__(self):
        self.chat = DummyChat()


def test_analyze_user_query_raises_when_groq_fails(monkeypatch):
    """If Groq fails and no other AI provider is configured, analysis should raise."""
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    # Ensure no other AI fallbacks are configured
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.delenv("CLOUDFLARE_AI_ENDPOINT", raising=False)

    bc = BibliometricCrawler()
    # Inject a client that raises
    bc.groq_client = DummyClient()

    with pytest.raises(RuntimeError):
        bc.analyze_user_query("data mining")


class DummyChatNonJson:
    class Comp:
        def create(self, *args, **kwargs):
            class R:
                class ChoiceMsg:
                    class Message:
                        content = "This is not JSON"

                    def __init__(self):
                        self.message = self.Message()

                def __init__(self):
                    self.choices = [self.ChoiceMsg()]

            return R()


class DummyClientNonJson:
    def __init__(self):
        self.chat = DummyChatNonJson()


def test_analyze_user_query_raises_on_non_json_response(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.delenv("CLOUDFLARE_AI_ENDPOINT", raising=False)

    bc = BibliometricCrawler()
    bc.groq_client = DummyClientNonJson()

    with pytest.raises(RuntimeError):
        bc.analyze_user_query("machine learning in medicine")


def test_analyze_user_query_cloudflare_fallback(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "fake-token")
    monkeypatch.setenv("CLOUDFLARE_AI_ENDPOINT", "https://api.cloudflare.example/v1/ai")

    class RaisingClient:
        class chat:
            class completions:
                @staticmethod
                def create(*args, **kwargs):
                    raise Exception("simulated groq failure")

    bc = BibliometricCrawler()
    bc.groq_client = RaisingClient()

    # Simulate Cloudflare response
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": '{"search_terms":["mm"],"databases":["pubmed"],"filters":{},"normalized_query":"mm"}'}}]}

    def fake_post(url, headers, json, timeout):
        return Resp()

    import requests

    monkeypatch.setattr(requests, "post", fake_post)

    analysis = bc.analyze_user_query("mm")
    assert analysis.get("_ai_provider", {}).get("provider") == "cloudflare"


def test_filter_and_normalize_results_cloudflare_fallback(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "fake-token")
    monkeypatch.setenv("CLOUDFLARE_AI_ENDPOINT", "https://api.cloudflare.example/v1/ai")

    class RaisingClient:
        class chat:
            class completions:
                @staticmethod
                def create(*args, **kwargs):
                    raise Exception("simulated groq failure")

    bc = BibliometricCrawler()
    bc.groq_client = RaisingClient()

    class Resp2:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": '{"normalization_rules":{"data-mining":"data mining"},"deduplication_strategy":"titles","relevance_criteria":["citation"],"recommended_filters":[]}'} }]}

    def fake_post2(url, headers, json, timeout):
        return Resp2()

    import requests

    monkeypatch.setattr(requests, "post", fake_post2)

    res = bc.filter_and_normalize_results({"pubmed": [{"title": "A"}]}, "data mining")
    assert res.get("filtering_provider", {}).get("provider") == "cloudflare"
    assert res.get("filtering_guidance", {}).get("normalization_rules", {}).get("data-mining") == "data mining"
