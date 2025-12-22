"""
Basic tests for the bibliometric crawler
These tests verify the structure and basic functionality without requiring API keys
"""

import os
import sys
import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawlers import (
    EBSCOCrawler,
    ERICCrawler,
    GeneCrawler,
    GenomeCrawler,
    IEEECrawler,
    PubChemCrawler,
    PubMedCrawler,
    SAGECrawler,
    ScienceDirectCrawler,
    ScopusCrawler,
    SpringerCrawler,
    WileyCrawler,
    WoSCrawler,
)


def test_crawler_instantiation():
    """Test that all crawler classes can be instantiated"""
    print("Testing crawler instantiation...")

    crawlers = [
        WoSCrawler,
        ScopusCrawler,
        ScienceDirectCrawler,
        PubMedCrawler,
        PubChemCrawler,
        GeneCrawler,
        GenomeCrawler,
        SAGECrawler,
        IEEECrawler,
        ERICCrawler,
        SpringerCrawler,
        EBSCOCrawler,
        WileyCrawler,
    ]

    for crawler_class in crawlers:
        try:
            crawler = crawler_class()
            assert crawler is not None
            assert hasattr(crawler, "search")
            assert hasattr(crawler, "base_url")
            print(f"  ✓ {crawler_class.__name__} instantiated successfully")
        except Exception as e:
            pytest.fail(f"{crawler_class.__name__} failed: {e}")


def test_crawler_search_method():
    """Test that search methods can be called (will return empty results)"""
    print("\nTesting search method calls...")

    crawlers = {
        "WoS": WoSCrawler(),
        "Scopus": ScopusCrawler(),
        "PubMed": PubMedCrawler(),
    }

    for name, crawler in crawlers.items():
        try:
            results = crawler.search("test query", max_results=10)
            assert isinstance(results, list)
            print(f"  ✓ {name} search method works (returned {len(results)} results)")
        except Exception as e:
            pytest.fail(f"{name} search method failed: {e}")


def test_base_crawler_methods():
    """Test base crawler helper methods"""
    print("\nTesting base crawler methods...")

    # Use a mock key for testing
    test_key = "test_key_for_testing_only"
    crawler = WoSCrawler(api_key=test_key)

    # Test header generation
    headers = crawler._get_headers()
    assert "Accept" in headers
    assert "X-ApiKey" in headers
    print("  ✓ Headers generation works")

    # Test without API key
    crawler2 = PubMedCrawler()
    headers2 = crawler2._get_headers()
    assert "Accept" in headers2
    print("  ✓ Headers work without API key")


def test_bibliometric_crawler_without_api():
    """Test that BibliometricCrawler can be imported (but not run without API key)"""
    print("\nTesting BibliometricCrawler import...")

    try:
        # This will work even without API keys (it will fail later when actually used)
        import bibliometric_crawler

        assert hasattr(bibliometric_crawler, "BibliometricCrawler")
        print("  ✓ BibliometricCrawler module imports successfully")
    except ImportError as e:
        pytest.fail(f"Failed to import: {e}")


def test_optional_package_flags():
    """Test that optional package flags are exposed and of correct type"""
    print("\nTesting optional package flags...")

    try:
        import crawlers
    except Exception as e:
        pytest.fail(f"Failed to import crawlers module: {e}")

    flags = [
        "PUBCHEMPY_AVAILABLE",
        "CROSSREF_AVAILABLE",
        "BIOPYTHON_AVAILABLE",
        "CEREBRAS_AVAILABLE",
    ]

    for f in flags:
        try:
            assert hasattr(crawlers, f)
            val = getattr(crawlers, f)
            assert isinstance(val, bool)
            print(f"  ✓ {f} present and is boolean: {val}")
        except Exception as e:
            pytest.fail(f"{f} not present or not boolean: {e}")


def test_visualize_pyvis_html_generation():
    """Test that visualize_pyvis can generate an HTML file using spring layout (fallback)."""
    print("\nTesting visualize_pyvis HTML generation (spring fallback)...")
    try:
        import tempfile

        from bibliometrics import visualize_pyvis

        # pyvis and networkx are optional in some environments; skip gracefully if missing
        try:
            from pyvis.network import Network  # noqa: F401
        except Exception as e:
            pytest.skip(f"pyvis not available; skipping visualize_pyvis test: {e}")
        try:
            import networkx as nx  # type: ignore
        except Exception as e:
            pytest.skip(f"networkx not available; skipping visualize_pyvis test: {e}")
    except Exception as e:
        pytest.skip(f"Required modules not available: {e}")

    # Build a minimal graph
    G = nx.Graph()
    G.add_node("Alice", n_pubs=3, display_name="Alice Example")
    G.add_node("Bob", n_pubs=2, display_name="Bob Example")
    G.add_edge("Alice", "Bob", weight=1)

    tmpdir = tempfile.mkdtemp(prefix="test_viz_")
    out_html = os.path.join(tmpdir, "test_vis.html")
    try:
        visualize_pyvis(
            G, out_html, notebook=False, layout="spring", spring_iterations=10, seed=1
        )
        if not os.path.exists(out_html):
            pytest.fail("visualize_pyvis did not write the expected HTML file.")
        print("  ✓ visualize_pyvis wrote HTML:", out_html)
    except Exception as e:
        pytest.fail(f"visualize_pyvis failed: {e}")


def test_jobs_inprocess_basic():
    """Basic test for the in-process job backend (direct InProcessBackend usage)."""
    print("\nTesting in-process job backend (direct InProcessBackend)...")
    try:
        from jobs import InProcessBackend
    except Exception as e:
        pytest.skip(f"InProcessBackend not available; skipping: {e}")

    backend = InProcessBackend(max_workers=1)

    # simple task to verify functionality
    def _add(a, b):
        return a + b

    try:
        job_id = backend.submit(_add, 1, 2)
    except Exception as e:
        pytest.fail(f"Failed to submit job to InProcessBackend: {e}")

    finished = False
    import time

    for _ in range(50):
        info = backend.status(job_id)
        if info and info.get("status") == "finished":
            finished = True
            break
        time.sleep(0.05)

    if not finished:
        pytest.fail(f"Job did not finish in time: {info}")

    try:
        res = backend.result(job_id, timeout=1)
        if res == 3:
            print("  ✓ in-process job backend (direct) works")
        else:
            pytest.fail(f"Unexpected job result: {res}")
    except Exception as e:
        pytest.fail(f"Failed to retrieve job result from InProcessBackend: {e}")


def test_cache_utils_basic():
    """Basic tests for cache utilities (set/get/clear)."""
    print("\nTesting cache utilities...")
    try:
        import cache_utils
    except Exception as e:
        pytest.skip(f"cache_utils not available; skipping cache tests: {e}")

    # Ensure a clean slate
    try:
        cache_utils.clear_cache()
    except Exception:
        pass

    key = cache_utils.make_cache_key("test", "cache", 1)
    try:
        cache_utils.set_cache(key, {"a": 1})
        v = cache_utils.get_cache(key)
        assert v == {"a": 1}
        print("  ✓ cache set/get works")
    except Exception as e:
        pytest.fail(f"cache set/get failed: {e}")

    try:
        cache_utils.clear_cache()
        v2 = cache_utils.get_cache(key)
        assert v2 is None
        print("  ✓ cache clear works")
    except Exception as e:
        pytest.fail(f"cache clear failed: {e}")


def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("Running Bibliometric Crawler Tests")
    print("=" * 60 + "\n")

    tests = [
        test_crawler_instantiation,
        test_crawler_search_method,
        test_base_crawler_methods,
        test_bibliometric_crawler_without_api,
        test_optional_package_flags,
        test_cache_utils_basic,
        test_jobs_inprocess_basic,
        test_visualize_pyvis_html_generation,
    ]

    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"\n✗ Test {test.__name__} crashed: {e}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print("\n" + "=" * 60)
    print(f"Test Results: {sum(results)}/{len(results)} passed")
    print("=" * 60)

    return all(results)


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
