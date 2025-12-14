"""
Basic tests for the bibliometric crawler
These tests verify the structure and basic functionality without requiring API keys
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crawlers import (
    BaseCrawler, WoSCrawler, ScopusCrawler, ScienceDirectCrawler,
    PubMedCrawler, PubChemCrawler, GeneCrawler, GenomeCrawler,
    SAGECrawler, IEEECrawler, ERICCrawler,
    SpringerCrawler, EBSCOCrawler, WileyCrawler
)


def test_crawler_instantiation():
    """Test that all crawler classes can be instantiated"""
    print("Testing crawler instantiation...")
    
    crawlers = [
        WoSCrawler, ScopusCrawler, ScienceDirectCrawler,
        PubMedCrawler, PubChemCrawler, GeneCrawler, GenomeCrawler,
        SAGECrawler, IEEECrawler, ERICCrawler,
        SpringerCrawler, EBSCOCrawler, WileyCrawler
    ]
    
    for crawler_class in crawlers:
        try:
            crawler = crawler_class()
            assert crawler is not None
            assert hasattr(crawler, 'search')
            assert hasattr(crawler, 'base_url')
            print(f"  ✓ {crawler_class.__name__} instantiated successfully")
        except Exception as e:
            print(f"  ✗ {crawler_class.__name__} failed: {e}")
            return False
    
    return True


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
            print(f"  ✗ {name} search method failed: {e}")
            return False
    
    return True


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
    
    return True


def test_bibliometric_crawler_without_api():
    """Test that BibliometricCrawler can be imported (but not run without API key)"""
    print("\nTesting BibliometricCrawler import...")
    
    try:
        # This will work even without API keys (it will fail later when actually used)
        import bibliometric_crawler
        assert hasattr(bibliometric_crawler, 'BibliometricCrawler')
        print("  ✓ BibliometricCrawler module imports successfully")
        return True
    except ImportError as e:
        print(f"  ✗ Failed to import: {e}")
        return False


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
