from perplexity import Perplexity
from dotenv import load_dotenv

load_dotenv()


def web_search(query: str):
    """
    Perform a web search using Perplexity API.
    
    Args:
        query (str): The search query
        
    Returns:
        str: Search results from Perplexity
    """
    client = Perplexity()
    
    completion = client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": query,
            }
        ],
        model="sonar",
    )
    
    return completion.choices[0].message.content

if __name__ == "__main__":
    print(web_search("dairy free hot chocolate restaurants Sarjapur Road Bangalore"))
