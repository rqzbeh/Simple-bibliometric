"""
Main bibliometric data crawler script with Groq AI integration.
Handles user queries, data retrieval, and AI-powered data filtering.
"""

import os
from typing import Dict, List, Any
from dotenv import load_dotenv
from groq import Groq
import json
from crawlers import (
    WoSCrawler, ScopusCrawler, ScienceDirectCrawler, PubMedCrawler,
    PubChemCrawler, GeneCrawler, GenomeCrawler, SAGECrawler,
    IEEECrawler, ERICCrawler, SpringerCrawler,
    EBSCOCrawler, WileyCrawler
)

# Load environment variables
load_dotenv()


class BibliometricCrawler:
    """Main orchestrator for bibliometric data crawling"""
    
    def __init__(self, groq_model: str = None):
        """Initialize the crawler with API keys and crawlers
        
        Args:
            groq_model: The Groq AI model to use (default: from env or llama-3.1-70b-versatile)
        """
        groq_api_key = os.getenv("GROQ_API_KEY")
        if not groq_api_key:
            raise ValueError(
                "GROQ_API_KEY not found in environment variables. "
                "Please set your Groq API key in the .env file or environment."
            )
        
        self.groq_client = Groq(api_key=groq_api_key)
        self.groq_model = groq_model or os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")
        
        # Initialize all crawlers
        self.crawlers = {
            "wos": WoSCrawler(os.getenv("WOS_API_KEY")),
            "scopus": ScopusCrawler(os.getenv("SCOPUS_API_KEY")),
            "sciencedirect": ScienceDirectCrawler(os.getenv("SCIENCEDIRECT_API_KEY")),
            "pubmed": PubMedCrawler(os.getenv("PUBMED_API_KEY")),
            "pubchem": PubChemCrawler(os.getenv("PUBCHEM_API_KEY")),
            "gene": GeneCrawler(os.getenv("GENE_API_KEY")),
            "genome": GenomeCrawler(os.getenv("GENOME_API_KEY")),
            "sage": SAGECrawler(os.getenv("SAGE_API_KEY")),
            "ieee": IEEECrawler(os.getenv("IEEE_API_KEY")),
            "eric": ERICCrawler(os.getenv("ERIC_API_KEY")),
            "springer": SpringerCrawler(os.getenv("SPRINGER_API_KEY")),
            "ebsco": EBSCOCrawler(os.getenv("EBSCO_API_KEY")),
            "wiley": WileyCrawler(os.getenv("WILEY_API_KEY"))
        }
    
    def analyze_user_query(self, user_query: str) -> Dict[str, Any]:
        """
        Use Groq AI to analyze the user's query and determine search parameters
        """
        system_prompt = """You are a bibliometric research assistant. Analyze the user's query and extract:
1. The main research topic or keywords
2. Potential search variations (e.g., "data mining" and "data-mining")
3. Relevant academic databases to search
4. Any specific filters or constraints

Return your analysis as a JSON object with these keys:
- search_terms: list of search terms and variations
- databases: list of relevant databases (use: wos, scopus, sciencedirect, pubmed, pubchem, gene, genome, sage, ieee, eric, springer, ebsco, wiley)
- filters: any date ranges, publication types, or other filters
- normalized_query: a standardized version of the query for searching"""

        try:
            response = self.groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query}
                ],
                model=self.groq_model,
                temperature=0.3,
                max_tokens=1000
            )
            
            analysis_text = response.choices[0].message.content
            
            # Try to extract JSON from the response
            try:
                # Find JSON in the response (it might be wrapped in markdown code blocks)
                if "```json" in analysis_text:
                    json_start = analysis_text.find("```json") + 7
                    json_end = analysis_text.find("```", json_start)
                    analysis_text = analysis_text[json_start:json_end]
                elif "```" in analysis_text:
                    json_start = analysis_text.find("```") + 3
                    json_end = analysis_text.find("```", json_start)
                    analysis_text = analysis_text[json_start:json_end]
                
                analysis = json.loads(analysis_text.strip())
            except json.JSONDecodeError:
                # Fallback: create a basic analysis
                analysis = {
                    "search_terms": [user_query],
                    "databases": list(self.crawlers.keys()),
                    "filters": {},
                    "normalized_query": user_query
                }
            
            return analysis
            
        except Exception as e:
            print(f"Error analyzing query with Groq AI: {e}")
            # Return a basic analysis as fallback
            return {
                "search_terms": [user_query],
                "databases": list(self.crawlers.keys()),
                "filters": {},
                "normalized_query": user_query
            }
    
    def crawl_databases(self, analysis: Dict[str, Any], max_results: int = 100) -> Dict[str, List[Dict[str, Any]]]:
        """
        Crawl the selected databases based on the analysis
        """
        results = {}
        search_terms = analysis.get("search_terms", [analysis.get("normalized_query", "")])
        databases = analysis.get("databases", list(self.crawlers.keys()))
        
        print(f"\nCrawling {len(databases)} databases for: {search_terms}")
        print("=" * 60)
        
        for db_name in databases:
            if db_name in self.crawlers:
                crawler = self.crawlers[db_name]
                db_results = []
                
                # Search with each term variation
                for term in search_terms:
                    try:
                        term_results = crawler.search(term, max_results)
                        db_results.extend(term_results)
                    except Exception as e:
                        print(f"Error crawling {db_name} for '{term}': {e}")
                
                results[db_name] = db_results
        
        return results
    
    def filter_and_normalize_results(self, raw_results: Dict[str, List[Dict[str, Any]]], 
                                     user_query: str) -> Dict[str, Any]:
        """
        Use Groq AI to filter and normalize results, combining similar entries
        """
        # Prepare a summary of results for AI processing
        result_summary = {}
        total_results = 0
        
        for db_name, results in raw_results.items():
            result_summary[db_name] = len(results)
            total_results += len(results)
        
        print(f"\n\nProcessing {total_results} total results with Groq AI...")
        print("=" * 60)
        
        filter_prompt = f"""Given bibliometric search results for the query: "{user_query}"

Task: Analyze and provide guidance on filtering and normalizing these results:
1. Identify potential duplicate entries (e.g., "data mining" vs "data-mining")
2. Suggest normalization rules for combining similar terms
3. Recommend how to deduplicate results across databases
4. Provide a strategy for ranking/filtering the most relevant results

Result counts by database:
{json.dumps(result_summary, indent=2)}

Provide your analysis as a JSON object with:
- normalization_rules: dict mapping variations to canonical forms
- deduplication_strategy: description of how to identify duplicates
- relevance_criteria: list of criteria for ranking results
- recommended_filters: any filters to apply"""

        try:
            response = self.groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are a bibliometric data analyst. Provide structured guidance for data normalization and filtering."},
                    {"role": "user", "content": filter_prompt}
                ],
                model=self.groq_model,
                temperature=0.3,
                max_tokens=1500
            )
            
            filtering_guidance = response.choices[0].message.content
            print("\nAI Filtering Guidance:")
            print(filtering_guidance)
            
            # Try to extract JSON guidance
            try:
                if "```json" in filtering_guidance:
                    json_start = filtering_guidance.find("```json") + 7
                    json_end = filtering_guidance.find("```", json_start)
                    filtering_guidance = filtering_guidance[json_start:json_end]
                elif "```" in filtering_guidance:
                    json_start = filtering_guidance.find("```") + 3
                    json_end = filtering_guidance.find("```", json_start)
                    filtering_guidance = filtering_guidance[json_start:json_end]
                
                guidance = json.loads(filtering_guidance.strip())
            except json.JSONDecodeError:
                guidance = {
                    "normalization_rules": {},
                    "deduplication_strategy": "Compare titles and DOIs",
                    "relevance_criteria": ["Recent publications", "Citation count", "Relevance to query"],
                    "recommended_filters": []
                }
            
        except Exception as e:
            print(f"Error getting filtering guidance: {e}")
            guidance = {
                "normalization_rules": {},
                "deduplication_strategy": "Compare titles and DOIs",
                "relevance_criteria": ["Recent publications", "Citation count", "Relevance to query"],
                "recommended_filters": []
            }
        
        # Return both raw results and filtering guidance
        return {
            "raw_results": raw_results,
            "result_summary": result_summary,
            "total_results": total_results,
            "filtering_guidance": guidance,
            "user_query": user_query
        }
    
    def process_query(self, user_query: str, max_results: int = 100) -> Dict[str, Any]:
        """
        Main entry point: process a user query end-to-end
        """
        print(f"\n{'=' * 60}")
        print(f"Processing query: {user_query}")
        print(f"{'=' * 60}\n")
        
        # Step 1: Analyze query with AI
        print("Step 1: Analyzing query with Groq AI...")
        analysis = self.analyze_user_query(user_query)
        print(f"Analysis complete:")
        print(f"  - Search terms: {analysis.get('search_terms', [])}")
        print(f"  - Databases: {analysis.get('databases', [])}")
        print(f"  - Normalized query: {analysis.get('normalized_query', '')}")
        
        # Step 2: Crawl databases
        print("\nStep 2: Crawling academic databases...")
        raw_results = self.crawl_databases(analysis, max_results)
        
        # Step 3: Filter and normalize with AI
        print("\nStep 3: Filtering and normalizing results with AI...")
        processed_results = self.filter_and_normalize_results(raw_results, user_query)
        
        return processed_results


def main():
    """Main function for CLI usage"""
    print("Bibliometric Data Crawler with Groq AI")
    print("=" * 60)
    
    # Check for API key
    if not os.getenv("GROQ_API_KEY"):
        print("ERROR: GROQ_API_KEY not found in environment variables.")
        print("Please create a .env file with your API keys.")
        print("See .env.example for reference.")
        return
    
    # Initialize crawler
    try:
        crawler = BibliometricCrawler()
    except ValueError as e:
        print(f"ERROR: {e}")
        return
    
    # Get user query
    print("\nEnter your research query (or 'quit' to exit):")
    while True:
        user_query = input("\n> ").strip()
        
        if user_query.lower() in ['quit', 'exit', 'q']:
            print("Goodbye!")
            break
        
        if not user_query:
            continue
        
        # Process the query
        try:
            results = crawler.process_query(user_query)
            
            print("\n" + "=" * 60)
            print("RESULTS SUMMARY")
            print("=" * 60)
            print(json.dumps(results["result_summary"], indent=2))
            print(f"\nTotal results found: {results['total_results']}")
            
        except Exception as e:
            print(f"Error processing query: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
