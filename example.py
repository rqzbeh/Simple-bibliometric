"""
Example usage of the bibliometric crawler
"""

from bibliometric_crawler import BibliometricCrawler
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def example_basic_search():
    """Basic search example"""
    print("=" * 60)
    print("Example 1: Basic Search")
    print("=" * 60)
    
    crawler = BibliometricCrawler()
    results = crawler.process_query("machine learning in healthcare")
    
    print("\n\nFinal Results:")
    print(f"Total results found: {results['total_results']}")
    print("\nResults by database:")
    for db, count in results['result_summary'].items():
        print(f"  - {db}: {count} results")


def example_with_filtering():
    """Example showing AI filtering guidance"""
    print("\n\n" + "=" * 60)
    print("Example 2: Query with AI Filtering")
    print("=" * 60)
    
    crawler = BibliometricCrawler()
    results = crawler.process_query("data mining")
    
    print("\n\nFiltering Guidance from AI:")
    guidance = results['filtering_guidance']
    print(f"Normalization rules: {guidance.get('normalization_rules', {})}")
    print(f"Deduplication strategy: {guidance.get('deduplication_strategy', 'N/A')}")
    print(f"Relevance criteria: {guidance.get('relevance_criteria', [])}")


def example_programmatic_access():
    """Example of programmatic access to crawler components"""
    print("\n\n" + "=" * 60)
    print("Example 3: Programmatic Access")
    print("=" * 60)
    
    crawler = BibliometricCrawler()
    
    # Step 1: Analyze query only
    print("\nStep 1: Analyzing query...")
    analysis = crawler.analyze_user_query("natural language processing")
    print(f"Extracted search terms: {analysis.get('search_terms', [])}")
    print(f"Recommended databases: {analysis.get('databases', [])}")
    
    # Step 2: Crawl specific databases
    print("\nStep 2: Crawling databases...")
    raw_results = crawler.crawl_databases(analysis, max_results=50)
    
    # Step 3: Process results
    print("\nStep 3: Processing results...")
    processed = crawler.filter_and_normalize_results(raw_results, "natural language processing")
    print(f"Total results: {processed['total_results']}")


if __name__ == "__main__":
    # Check for API key
    if not os.getenv("GROQ_API_KEY"):
        print("ERROR: GROQ_API_KEY not found in environment variables.")
        print("Please create a .env file with your Groq API key.")
        print("See .env.example for reference.")
        exit(1)
    
    # Run examples
    try:
        example_basic_search()
        example_with_filtering()
        example_programmatic_access()
        
        print("\n\n" + "=" * 60)
        print("Examples completed successfully!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\nError running examples: {e}")
        import traceback
        traceback.print_exc()
