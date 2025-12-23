import pytest

from bibliometric_crawler import BibliometricCrawler


def test_check_api_keys_reports_presence_and_absence(monkeypatch):
    # Required for BibliometricCrawler initialization
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")

    # Set a couple of crawler keys and leave others unset
    monkeypatch.setenv("WOS_API_KEY", "wos-key")
    monkeypatch.setenv("SCOPUS_API_KEY", "scopus-key")
    monkeypatch.delenv("PUBCHEM_API_KEY", raising=False)

    bc = BibliometricCrawler()
    keys = bc.check_api_keys()

    assert keys["wos"]["present"] is True
    assert keys["wos"]["env"] == "WOS_API_KEY"
    assert keys["pubchem"]["present"] is False

    missing = bc.get_missing_api_keys()
    assert "pubchem" in missing
    assert missing["pubchem"] == "PUBCHEM_API_KEY"


def test_check_api_keys_all_present(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    # Set all known keys to some dummy value
    envs = [
        "WOS_API_KEY",
        "SCOPUS_API_KEY",
        "SCIENCEDIRECT_API_KEY",
        "PUBMED_API_KEY",
        "PUBCHEM_API_KEY",
        "GENE_API_KEY",
        "GENOME_API_KEY",
        "SAGE_API_KEY",
        "IEEE_API_KEY",
        "ERIC_API_KEY",
        "SPRINGER_API_KEY",
        "EBSCO_API_KEY",
        "WILEY_API_KEY",
    ]
    for e in envs:
        monkeypatch.setenv(e, "dummy")

    bc = BibliometricCrawler()
    missing = bc.get_missing_api_keys()
    assert missing == {}
