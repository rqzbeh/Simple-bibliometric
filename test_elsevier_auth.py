import xml.etree.ElementTree as ET
import time

import requests


class FakeAuthResponse:
    def __init__(self, text):
        self.text = text
        self.status_code = 200
        self.headers = {"Content-Type": "text/xml"}

    def raise_for_status(self):
        return None

    def json(self):
        # not used for this fake
        return {}


class FakeSearchResponse:
    def __init__(self):
        self.status_code = 200
        self.headers = {"Content-Type": "application/json"}

    def raise_for_status(self):
        return None

    def json(self):
        return {"search-results": {"entry": []}}


def test_scopus_authtoken_exchange_and_header(monkeypatch):
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append({"url": url, "headers": headers, "params": params})
        if 'authenticate' in url:
            return FakeAuthResponse('<authenticate-response><authtoken>MYTOKEN</authtoken></authenticate-response>')
        return FakeSearchResponse()

    monkeypatch.setattr('requests.get', fake_get)

    from crawlers import ScopusCrawler

    c = ScopusCrawler(api_key='KEY123')
    c.search('test', max_results=1)

    # Ensure authenticate was called
    auth_call = next(x for x in calls if 'authenticate' in x['url'])
    assert auth_call['headers'].get('X-ELS-APIKey') == 'KEY123'

    # Ensure subsequent search included authtoken in headers
    search_call = next(x for x in calls if 'search/scopus' in x['url'])
    assert 'X-ELS-AuthToken' in search_call['headers'] or 'X-ELS-Authtoken' in search_call['headers']


def test_sciencedirect_authtoken_exchange_and_insttoken(monkeypatch):
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append({"url": url, "headers": headers, "params": params})
        if 'authenticate' in url:
            return FakeAuthResponse('<authenticate-response><authtoken>SDTOKEN</authtoken></authenticate-response>')
        return FakeSearchResponse()

    monkeypatch.setattr('requests.get', fake_get)

    import os

    os.environ['ELS_INSTTOKEN'] = 'INST123'

    from crawlers import ScienceDirectCrawler

    c = ScienceDirectCrawler(api_key='SDKEY')
    c.search('test', max_results=1)

    search_call = next(x for x in calls if 'search/sciencedirect' in x['url'])
    hdrs = search_call['headers']
    assert hdrs.get('X-ELS-APIKey') == 'SDKEY'
    assert hdrs.get('X-ELS-Insttoken') == 'INST123'
    assert 'X-ELS-AuthToken' in hdrs or 'X-ELS-Authtoken' in hdrs