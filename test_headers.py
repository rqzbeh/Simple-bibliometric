import json

import requests


def test_wos_headers_sent(monkeypatch):
    sent = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        sent['url'] = url
        sent['params'] = params
        sent['headers'] = headers

        class R:
            status_code = 200
            headers = {'Content-Type': 'application/json'}

            def json(self):
                # minimal shape expected by WoSCrawler.search
                return {'Data': {'Records': {'records': []}}}

            def raise_for_status(self):
                return None

            text = ''

        return R()

    monkeypatch.setattr('requests.get', fake_get)

    from crawlers import WoSCrawler

    c = WoSCrawler(api_key='MY_WOS_KEY')
    c.search('test', max_results=1)

    assert 'headers' in sent
    h = sent['headers']
    assert h.get('X-ApiKey') == 'MY_WOS_KEY'


def test_scopus_and_sciencedirect_headers_sent(monkeypatch):
    sent = []

    def fake_get(url, params=None, headers=None, timeout=None):
        sent.append({'url': url, 'headers': headers})

        class R:
            status_code = 200
            headers = {'Content-Type': 'application/json'}

            def json(self):
                # return a minimal structure compatible with Scopus/ScienceDirect parsing
                return {'search-results': {'entry': []}}

            def raise_for_status(self):
                return None

            text = ''

        return R()

    monkeypatch.setattr('requests.get', fake_get)

    from crawlers import ScopusCrawler, ScienceDirectCrawler

    sc = ScopusCrawler(api_key='MY_SCOPUS_KEY')
    sd = ScienceDirectCrawler(api_key='MY_SD_KEY')

    sc.search('test', max_results=1)
    sd.search('test', max_results=1)

    # Find relevant entries
    sc_entry = next(item for item in sent if 'search/scopus' in item['url'])
    sd_entry = next(item for item in sent if 'search/sciencedirect' in item['url'])

    assert sc_entry['headers'].get('X-ELS-APIKey') == 'MY_SCOPUS_KEY'
    assert sc_entry['headers'].get('X-ELS-ApiKey') == 'MY_SCOPUS_KEY'
    assert sd_entry['headers'].get('X-ELS-APIKey') == 'MY_SD_KEY'