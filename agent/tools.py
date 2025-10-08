import os
from tavily import TavilyClient

from dotenv import load_dotenv

load_dotenv()

def web_search(query: str):
    """
    Perform a web search using Tavily API.
    
    Args:
        query (str): The search query
        
    Returns:
        dict: Search results from Tavily
    """
    # Get API key from environment variable
    api_key = os.getenv('TAVILY_API_KEY')
    if not api_key:
        raise ValueError("TAVILY_API_KEY environment variable is required")
    
    # Initialize Tavily client
    tavily_client = TavilyClient(api_key=api_key)
    
    # Execute search
    response = tavily_client.search(query)
    
    return response
