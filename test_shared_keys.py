import pytest

from bibliometric_crawler import BibliometricCrawler


def test_ncbi_sharing_fallback(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    # Only set the PUBMED key; pubchem/gene/genome should pick it up via fallback
    monkeypatch.setenv("PUBMED_API_KEY", "pubmed-key")
    monkeypatch.delenv("PUBCHEM_API_KEY", raising=False)
    monkeypatch.delenv("GENE_API_KEY", raising=False)
    monkeypatch.delenv("GENOME_API_KEY", raising=False)

    bc = BibliometricCrawler()
    eff = bc.get_effective_api_keys()

    assert eff["pubmed"] == "pubmed-key"
    assert eff["pubchem"] == "pubmed-key"
    assert eff["gene"] == "pubmed-key"
    assert eff["genome"] == "pubmed-key"


def test_elsevier_sharing_fallback(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    # Only set SCOPUS key, sciencedirect should pick it up
    monkeypatch.setenv("SCOPUS_API_KEY", "scopus-key")
    monkeypatch.delenv("SCIENCEDIRECT_API_KEY", raising=False)

    bc = BibliometricCrawler()
    eff = bc.get_effective_api_keys()

    assert eff["scopus"] == "scopus-key"
    assert eff["sciencedirect"] == "scopus-key"
