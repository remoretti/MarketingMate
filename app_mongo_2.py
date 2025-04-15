import streamlit as st
import requests
import feedparser
import pandas as pd
from bs4 import BeautifulSoup
import openai
import os
from dotenv import load_dotenv
from openai import OpenAI
from prompts import prompt_dict
import json
from typing import TypedDict, Dict
from langgraph.graph import StateGraph, END
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage
from pymongo import MongoClient
from datetime import datetime, timedelta

st.set_page_config(layout="wide")

# Load environment variables
load_dotenv()  # Loads variables from .env into os.environ

# Configure OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY")

# Retrieve MongoDB connection details from .env (for local instance, e.g., "mongodb://localhost:27017/")
MONGO_URI = os.getenv("MONGO_URI")
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["MarketingMate"]
articles_collection = db["articles"]

# ---------------------------
# Helper Functions & Globals
# ---------------------------
def display_recent_update():
    # Get all articles from MongoDB.
    articles = list(articles_collection.find())
    if articles:
        df_inspect = pd.DataFrame(articles)
        # Convert the "timestamp" field to datetime.
        df_inspect["timestamp_parsed"] = pd.to_datetime(df_inspect["timestamp"], errors="coerce")
        most_recent = df_inspect["timestamp_parsed"].max()
        if pd.notnull(most_recent):
            st.write(f"Most Recent Article Released On: {most_recent.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            st.write("Could not parse timestamps.")
    else:
        st.write("No articles found in MongoDB.")

def get_article_text(url):
    """Fetches the full article text from the URL by parsing HTML paragraphs."""
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; MyRSSReader/1.0)'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        html = response.text
        soup = BeautifulSoup(html, "html.parser")
        paragraphs = soup.find_all("p")
        return "\n".join([p.get_text() for p in paragraphs])
    except Exception as e:
        st.error(f"Error fetching article content from {url}: {e}")
        return ""

# Define the state for each article.
class ArticleState(TypedDict):
    text: str                 # Full article content (fetched from the URL)
    ranking: Dict[str, int]   # To be populated by the ranking node
    timestamp: str            # RSS feed timestamp
    summary: str              # RSS feed summary
    source: str               # RSS source name

# Initialize the LLM for the LangGraph agent.
llm = ChatOpenAI(model="gpt-4o-mini", temperature=1)

# Define the ranking node.
def ranking_node(state: ArticleState):
    prompt = PromptTemplate(
        input_variables=["text"],
        template="""
        Analyze the following article content and provide a relevance score (0-15) for each of the following topics:
        - Digital Transformation
        - Generative AI
        - Machine Learning / Data Science
        - Finance in tech

        Guidelines:
        0-5: low relevance
        6-10: medium relevance
        11-15: high relevance

        Return only a JSON object exactly in this format:
        {{
        "Digital Transformation": score,
        "Generative AI": score,
        "Machine Learning / Data Science": score,
        "Finance in tech": score
        }}

        Do not include any additional text or explanation.

        Article content:
        {text}
        """
    )
    message = HumanMessage(content=prompt.format(text=state["text"]))
    ranking_result = llm.invoke([message]).content.strip()
    
    # Strip markdown code fences if present.
    if ranking_result.startswith("```"):
        ranking_result = ranking_result.replace("```", "").strip()
        if ranking_result.lower().startswith("json"):
            ranking_result = ranking_result[len("json"):].strip()
    
    if not ranking_result:
        st.error("LLM returned an empty response for ranking.")
        ranking_dict = {}
    else:
        try:
            ranking_dict = json.loads(ranking_result)
        except Exception as e:
            st.error(f"Error parsing ranking JSON: {e}. Raw output: {ranking_result}")
            ranking_dict = {}
    return {"ranking": ranking_dict}

# Build the LangGraph agent.
workflow = StateGraph(ArticleState)
workflow.add_node("ranking_node", ranking_node)
workflow.set_entry_point("ranking_node")
workflow.add_edge("ranking_node", END)
agent = workflow.compile()

def process_article(row):
    article_url = row["URL"]
    article_text = get_article_text(article_url)
    if not article_text:
        return None  # Skip if content retrieval fails.
    state_input: ArticleState = {
        "text": article_text,
        "ranking": {},
        "timestamp": row["Date Created"],
        "summary": row["Summary"],
        "source": row["RSS Source"]
    }
    result_state = agent.invoke(state_input)
    # Add the URL and Title for later persistence.
    result_state["url"] = article_url
    result_state["Title"] = row["Title"]  # Ensure the Title field is stored.
    
    # Transform the ranking into separate properties.
    ranking = result_state.get("ranking", {})
    if isinstance(ranking, str):
        try:
            ranking = json.loads(ranking)
        except Exception as e:
            ranking = {}
    result_state["digital_transformation"] = ranking.get("Digital Transformation", 0)
    result_state["generative_ai"] = ranking.get("Generative AI", 0)
    result_state["machine_learning"] = ranking.get("Machine Learning / Data Science", 0)
    result_state["finance_in_tech"] = ranking.get("Finance in tech", 0)
    return result_state

def persist_knowledge_base_mongo(knowledge_base):
    if knowledge_base:
        articles_collection.insert_many(knowledge_base)
        st.session_state.last_updated = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        st.success("Knowledge base persisted to MongoDB!")
    else:
        st.error("No knowledge base to persist.")

def fetch_feed(feed_url, source_name):
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; MyRSSReader/1.0)'}
    try:
        response = requests.get(feed_url, headers=headers, timeout=10)
        response.raise_for_status()
        content = response.content
    except Exception as e:
        st.error(f"Error fetching feed from {feed_url}: {e}")
        return []
    feed = feedparser.parse(content)
    entries = []
    if not feed.entries:
        st.warning(f"No entries found for {source_name} from {feed_url}")
    for entry in feed.entries:
        title = entry.title if 'title' in entry else 'No Title'
        link = entry.link if 'link' in entry else 'No URL'
        summary = entry.summary if 'summary' in entry else entry.get('description', 'No Summary')
        date_created = entry.published if 'published' in entry else entry.get('updated', 'No Date')
        entries.append({
            "RSS Source": source_name,
            "Title": title,
            "URL": link,
            "Summary": summary,
            "Date Created": date_created
        })
    return entries

@st.cache_data(show_spinner=False)
def get_all_feeds():
    all_entries = []
    feed_sources = {
        "https://www.404media.co/rss": "404 Media",
        "https://aiacceleratorinstitute.com/rss/": "AI Accelerator Institute",
        "https://aibusiness.com/rss.xml": "AI Business",
        "https://www.artificialintelligence-news.com/feed/rss/": "AI News",
        "https://www.theguardian.com/technology/artificialintelligenceai/rss": "The Guardian",
        "https://feeds.businessinsider.com/custom/all": "Business Insider"
    }
    for url, source in feed_sources.items():
        all_entries.extend(fetch_feed(url, source))
    df = pd.DataFrame(all_entries)
    if not df.empty:
        df = df[["RSS Source", "Title", "URL", "Summary", "Date Created"]]
    return df

# ---------------------------
# DATABASE MANAGEMENT SECTION
# ---------------------------
def database_management_section():
    st.markdown("### Database Inspection")
    count = articles_collection.count_documents({})
    st.write(f"Total documents in MongoDB: {count}")
    display_recent_update()
    if "last_updated" in st.session_state:
        st.write(f"Last updated: {st.session_state.last_updated}")
    
    # Load RSS feeds if not already loaded.
    if "rss_df" not in st.session_state:
        st.session_state.rss_df = get_all_feeds()
    # if st.button("Refresh RSS"):
    #     st.session_state.rss_df = get_all_feeds()
    df = st.session_state.rss_df

    # Removed "RSS Feed Overview" display.

    if st.button("Search for Updates"):
        with st.spinner("Processing articles..."):
            knowledge_base = []
            for idx, row in df.iterrows():
                # Check if the article (by Title and timestamp) already exists in MongoDB.
                existing = articles_collection.find_one({
                    "Title": row["Title"],
                    "timestamp": row["Date Created"]
                })
                if existing:
                    continue  # Skip processing duplicates without debug messages.
                processed = process_article(row)
                if processed:
                    knowledge_base.append(processed)
            st.session_state.knowledge_base = knowledge_base
            st.success(f"Knowledge Base updated with {len(knowledge_base)} new articles.")
    
    if "knowledge_base" in st.session_state and st.session_state.knowledge_base:
        st.markdown("### Updates Overview")
        knowledge_df = pd.DataFrame(st.session_state.knowledge_base)
        st.dataframe(knowledge_df)
        if st.button("Save Updates to MongoDB"):
            persist_knowledge_base_mongo(st.session_state.knowledge_base)
    
    else:
        st.error("No knowledge base to persist.")


# ---------------------------
# CONTENT CREATION SECTION
# ---------------------------
# ... [previous code remains unchanged above Content Creation Section]

def content_creation_section():
    st.markdown("# Content Creation")
    col1, col2 = st.columns([1, 2])
    with col1:
        # Retrieve articles from MongoDB and convert to a DataFrame.
        articles = list(articles_collection.find())
        if not articles:
            st.error("No articles found in the database. Please build and persist your knowledge base.")
            return
        df_db = pd.DataFrame(articles)
        # Convert timestamp string to datetime for filtering.
        df_db["timestamp_parsed"] = pd.to_datetime(df_db["timestamp"], errors="coerce")
        # --- Filter by Date ---
        st.markdown("#### Filters")
        date_filter_option = st.selectbox(
            "Time filter", 
            ["No Filter", "Last 24 hrs", "Last 3 days", "Last week", "Last month"]
        )
        if date_filter_option != "No Filter":
            now = datetime.utcnow()
            if date_filter_option == "Last 24 hrs":
                cutoff = now - timedelta(days=1)
            elif date_filter_option == "Last 3 days":
                cutoff = now - timedelta(days=3)
            elif date_filter_option == "Last week":
                cutoff = now - timedelta(days=7)
            elif date_filter_option == "Last month":
                cutoff = now - timedelta(days=30)
            df_db = df_db[df_db["timestamp_parsed"] >= cutoff]
        
                # --- Filter by Source ---
        source_filter_option = st.selectbox(
            "Filter by Source", 
            ["All"] + sorted(df_db["source"].unique().tolist())
        )
        if source_filter_option != "All":
            df_db = df_db[df_db["source"] == source_filter_option]
        
        # --- Filter by Relevance ---
        dt_threshold = st.slider("Digital Transformation", 0, 15, 0)
        ga_threshold = st.slider("Generative AI", 0, 15, 0)
        ml_threshold = st.slider("Machine Learning / Data Science", 0, 15, 0)
        ft_threshold = st.slider("Finance in tech", 0, 15, 0)
        
        df_db = df_db[
            (df_db["digital_transformation"] >= dt_threshold) &
            (df_db["generative_ai"] >= ga_threshold) &
            (df_db["machine_learning"] >= ml_threshold) &
            (df_db["finance_in_tech"] >= ft_threshold)
        ]
    
    with col2:
    # --- Display Filtered Articles with Renamed Columns ---
        df_display = df_db[["Title", "source", "timestamp", "digital_transformation", "generative_ai", "machine_learning", "finance_in_tech", "url", "summary"]].copy()
        df_display_renamed = df_display.rename(columns={
            "source": "Source",
            "timestamp": "Released on",
            "digital_transformation": "Dig Transf",
            "generative_ai": "Gen AI",
            "machine_learning": "ML",
            "finance_in_tech": "FinTec"
        })
        
        st.markdown("#### Filtered Articles")
        # Display a DataFrame without the hidden fields.
        df_reset = df_display_renamed.drop(columns=["url", "summary"]).reset_index(drop=True)
        st.dataframe(df_reset, height=500)
    st.markdown("---")
        
    col3, col4, col5 = st.columns([1, 2, 2,])
    with col3:
        # --- Article Selection Section ---
        st.markdown("#### Article Selection")
        # --- Row Selection ---
        selected_title = st.selectbox("Select an Article (by title)", df_display_renamed["Title"].unique())
        selected_article = df_db[df_db["Title"] == selected_title].iloc[0]

        
        #st.write("**Title:**", selected_article["Title"])
        st.write("**Source:**", selected_article["source"])
        st.write("**Released on:**", selected_article["timestamp"])
        # Display the article text.
        #st.markdown("**Article Content:**")
        st.markdown("#### Select Output Form")
        form_choice = st.radio("Choose your output destination:", options=["LinkedIn", "Newsletter"])
        if form_choice == "Newsletter":
            specific_choice = st.radio("Select Newsletter frequency:", options=["Weekly", "Monthly"])
        elif form_choice == "LinkedIn":
            specific_choice = st.radio("Select LinkedIn post type:", options=[
                "New post", "Carousel", "Commercial post", "Erik's self branding"
            ])
    
    with col4:
        st.text_area("Full Article Text", selected_article["text"], height=800)
        article_url = selected_article["url"]
        article_text = get_article_text(article_url)
        if not article_text:
            st.error("Failed to retrieve article content.")
        else:
            if st.button("Confirm Choices"):
                prompt_key = (form_choice, specific_choice)
                if prompt_key not in prompt_dict:
                    st.error("No prompt defined for this combination.")
                else:
                    prompt_text = prompt_dict[prompt_key]
                    full_prompt = f"{prompt_text}\n\nArticle content:\n{article_text}"
                    st.info("Calling the language model for content generation...")
                    try:
                        client = OpenAI()
                        response = client.chat.completions.create(
                            model="o1-mini",
                            messages=[{"role": "user", "content": full_prompt}],
                            max_completion_tokens=5000,
                            temperature=1
                        )
                        llm_output = response.choices[0].message.content.strip()
                        st.session_state.llm_output = llm_output
                    except Exception as e:
                        st.error(f"Error during LLM call: {e}")    

    with col5:
        
            if "llm_output" in st.session_state:
                #st.markdown(f"### Proposed {form_choice} content")
                st.text_area(f"LLM Output for {form_choice} {specific_choice}", st.session_state.llm_output, height=800)


def app():
    st.title("MarketingMate")
    database_management_section()
    st.markdown("---")
    content_creation_section()

if __name__ == "__main__":
    app()
