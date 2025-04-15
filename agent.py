import json
from typing import TypedDict, Dict
import requests
from bs4 import BeautifulSoup

from langgraph.graph import StateGraph, END
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage

# Helper function to fetch full article text given a URL.
def get_article_text(url: str) -> str:
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; MyRSSReader/1.0)'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        html = response.text
        soup = BeautifulSoup(html, "html.parser")
        paragraphs = soup.find_all("p")
        text = "\n".join([p.get_text() for p in paragraphs])
        return text
    except Exception as e:
        print(f"Error fetching article content from {url}: {e}")
        return ""

# Define the state for each article.
class ArticleState(TypedDict):
    text: str                 # Full article content (fetched from the URL)
    ranking: Dict[str, int]   # To be populated by the ranking node
    timestamp: str            # RSS feed timestamp
    summary: str              # RSS feed summary
    source: str               # RSS source name

# Initialize your LLM (using your preferred model and temperature)
llm = ChatOpenAI(model="gpt-4o-mini", temperature=)

# Define the ranking node.
def ranking_node(state: ArticleState) -> dict:
    prompt = PromptTemplate(
        input_variables=["text"],
        template="""Analyze the following article content and provide a relevance score (0-15) for each of the following topics:
- Digital Transformation
- Generative AI
- Machine Learning / Data Science
- Finance in tech

Guidelines:
0-5: low relevance
6-10: medium relevance
11-15: high relevance

Return your answer in JSON format like:
{
  "Digital Transformation": score,
  "Generative AI": score,
  "Machine Learning / Data Science": score,
  "Finance in tech": score
}

Article content:
{text}"""
    )
    message = HumanMessage(content=prompt.format(text=state["text"]))
    ranking_result = llm.invoke([message]).content.strip()
    try:
        ranking_dict = json.loads(ranking_result)
    except Exception as e:
        print(f"Error parsing ranking result: {e}")
        ranking_dict = {}
    return {"ranking": ranking_dict}

# Build and compile the LangGraph agent.
def create_agent():
    workflow = StateGraph(ArticleState)
    workflow.add_node("ranking_node", ranking_node)
    workflow.set_entry_point("ranking_node")
    workflow.add_edge("ranking_node", END)
    agent = workflow.compile()
    return agent

# Helper function to process a single article (given an RSS feed row).
def process_article(row: dict) -> ArticleState:
    article_url = row["URL"]
    article_text = get_article_text(article_url)
    if not article_text:
        raise ValueError(f"No content fetched for URL: {article_url}")
    # Build the initial state from the RSS feed row.
    state_input: ArticleState = {
        "text": article_text,
        "ranking": {},  # Will be populated by the agent.
        "timestamp": row["Date Created"],
        "summary": row["Summary"],
        "source": row["RSS Source"]
    }
    agent = create_agent()
    result_state = agent.invoke(state_input)
    return result_state

# If running this file directly, test the agent with a sample article.
if __name__ == "__main__":
    # Example RSS feed row for testing.
    sample_row = {
        "URL": "https://example.com/sample-article",
        "Date Created": "2025-03-01T12:00:00Z",
        "Summary": "This is a sample summary provided by the RSS feed.",
        "RSS Source": "Example Source"
    }
    try:
        processed_article = process_article(sample_row)
        print("Processed Article State:")
        print(json.dumps(processed_article, indent=2))
    except Exception as e:
        print(f"Error processing sample article: {e}")
