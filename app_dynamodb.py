import streamlit as st
import requests
import feedparser
import pandas as pd
from bs4 import BeautifulSoup
import openai
import os
import boto3
from boto3.dynamodb.conditions import Key, Attr
from dotenv import load_dotenv
from openai import OpenAI
from prompts import prompt_dict
import json
from typing import TypedDict, Dict
from langgraph.graph import StateGraph, END
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage
from datetime import datetime, timedelta
import traceback

# Add AWS Credentials Verification
def verify_aws_credentials():
    try:
        # Similar explicit configuration
        sts_client = boto3.client(
            'sts', 
            region_name='us-east-1',
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
        )
        sts_client.get_caller_identity()
        return True
    except Exception as e:
        st.error(f"AWS Credentials Error: {e}")
        st.error(f"Full Error Details: {traceback.format_exc()}")
        return False

#st.set_page_config(layout="wide")

# Load environment variables
load_dotenv()  # Loads variables from .env into os.environ

# Configure OpenAI API key
openai.api_key = os.getenv("OPENAI_API_KEY")

# Retrieve DynamoDB connection details 
def get_dynamodb_table():
    try:
        # Explicitly print out configuration for debugging
        print("Region:", os.getenv('AWS_DEFAULT_REGION'))
        print("Access Key ID:", os.getenv('AWS_ACCESS_KEY_ID')[:4] + '...')

        # Create client with explicit configuration
        dynamodb = boto3.resource(
            'dynamodb', 
            region_name=os.getenv('AWS_DEFAULT_REGION', 'us-east-1'),
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
        )
        
        table = dynamodb.Table('MarketingMateDB')
        table.load()  # Verify table exists
        return table
    except Exception as e:
        # More detailed error logging
        st.error(f"DynamoDB Table Access Error: {e}")
        st.error(f"Full Error Details: {traceback.format_exc()}")
        return None

# Initialize DynamoDB table
table = get_dynamodb_table()

# ---------------------------
# Helper Functions & Globals
# ---------------------------
def display_recent_update():
    try:
        # Scan the entire table to get all items
        response = table.scan()
        articles = response.get('Items', [])
        
        if articles:
            df_inspect = pd.DataFrame(articles)
            # Convert the "timestamp" field to datetime
            df_inspect["timestamp_parsed"] = pd.to_datetime(df_inspect["timestamp"], errors="coerce")
            most_recent = df_inspect["timestamp_parsed"].max()
            
            if pd.notnull(most_recent):
                st.write(f"Most Recent Article Released On: {most_recent.strftime('%Y-%m-%d %H:%M:%S')}")
            else:
                st.write("Could not parse timestamps.")
        else:
            st.write("No articles found in DynamoDB.")
    except Exception as e:
        st.error(f"Error fetching recent update: {e}")

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

def persist_knowledge_base_dynamodb(knowledge_base):
    if knowledge_base:
        with table.batch_writer() as batch:
            for article in knowledge_base:
                # Add TTL (optional) - expire after 6 months
                article['ttl'] = int(datetime.utcnow().timestamp()) + (180 * 24 * 60 * 60)
                batch.put_item(Item=article)
        
        st.session_state.last_updated = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        st.success("Knowledge base persisted to DynamoDB!")
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
        #"https://aibusiness.com/rss.xml": "AI Business",
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
    
    # Count documents in DynamoDB
    response = table.scan(Select='COUNT')
    count = response['Count']
    st.write(f"Total documents in DynamoDB: {count}")
    
    display_recent_update()
    if "last_updated" in st.session_state:
        st.write(f"Last updated: {st.session_state.last_updated}")
    
    # Load RSS feeds if not already loaded
    if "rss_df" not in st.session_state:
        st.session_state.rss_df = get_all_feeds()
    
    df = st.session_state.rss_df

    if st.button("Search for Updates"):
        with st.spinner("Processing articles..."):
            knowledge_base = []
            for idx, row in df.iterrows():
                # Check if the article already exists in DynamoDB
                existing_response = table.scan(
                    FilterExpression=Attr('Title').eq(row["Title"]) & 
                                     Attr('timestamp').eq(row["Date Created"])
                )
                
                if existing_response['Count'] > 0:
                    continue  # Skip processing duplicates
                
                processed = process_article(row)
                if processed:
                    knowledge_base.append(processed)
            
            st.session_state.knowledge_base = knowledge_base
            st.success(f"Knowledge Base updated with {len(knowledge_base)} new articles.")
    
    if "knowledge_base" in st.session_state and st.session_state.knowledge_base:
        st.markdown("### Updates Overview")
        knowledge_df = pd.DataFrame(st.session_state.knowledge_base)
        st.dataframe(knowledge_df)
        
        if st.button("Save Updates to DynamoDB"):
            persist_knowledge_base_dynamodb(st.session_state.knowledge_base)
    
    else:
        st.error("No knowledge base to persist.")


# ---------------------------
# CONTENT CREATION SECTION
# ---------------------------
# ... [previous code remains unchanged above Content Creation Section]

# def content_creation_section():
#     st.markdown("# Content Creation")
#     col1, col2 = st.columns([1, 2])
    
#     with col1:
#         # Retrieve articles from DynamoDB
#         response = table.scan()
#         articles = response.get('Items', [])
        
#         if not articles:
#             st.error("No articles found in the database. Please build and persist your knowledge base.")
#             return
        
#         df_db = pd.DataFrame(articles)
        
#         # Convert timestamp string to datetime for filtering
#         df_db["timestamp_parsed"] = pd.to_datetime(df_db["timestamp"], errors="coerce")
#         # --- Filter by Date ---
#         st.markdown("#### Filters")
#         date_filter_option = st.selectbox(
#             "Time filter", 
#             ["No Filter", "Last 24 hrs", "Last 3 days", "Last week", "Last month"]
#         )
#         if date_filter_option != "No Filter":
#             now = datetime.utcnow()
#             if date_filter_option == "Last 24 hrs":
#                 cutoff = now - timedelta(days=1)
#             elif date_filter_option == "Last 3 days":
#                 cutoff = now - timedelta(days=3)
#             elif date_filter_option == "Last week":
#                 cutoff = now - timedelta(days=7)
#             elif date_filter_option == "Last month":
#                 cutoff = now - timedelta(days=30)
#             df_db = df_db[df_db["timestamp_parsed"] >= cutoff]
        
#                 # --- Filter by Source ---
#         source_filter_option = st.selectbox(
#             "Filter by Source", 
#             ["All"] + sorted(df_db["source"].unique().tolist())
#         )
#         if source_filter_option != "All":
#             df_db = df_db[df_db["source"] == source_filter_option]
        
#         # --- Filter by Relevance ---
#         dt_threshold = st.slider("Digital Transformation", 0, 15, 0)
#         ga_threshold = st.slider("Generative AI", 0, 15, 0)
#         ml_threshold = st.slider("Machine Learning / Data Science", 0, 15, 0)
#         ft_threshold = st.slider("Finance in tech", 0, 15, 0)
        
#         df_db = df_db[
#             (df_db["digital_transformation"] >= dt_threshold) &
#             (df_db["generative_ai"] >= ga_threshold) &
#             (df_db["machine_learning"] >= ml_threshold) &
#             (df_db["finance_in_tech"] >= ft_threshold)
#         ]
    
#     with col2:
#     # --- Display Filtered Articles with Renamed Columns ---
#         df_display = df_db[["Title", "source", "timestamp", "digital_transformation", "generative_ai", "machine_learning", "finance_in_tech", "url", "summary"]].copy()
#         df_display_renamed = df_display.rename(columns={
#             "source": "Source",
#             "timestamp": "Released on",
#             "digital_transformation": "Dig Transf",
#             "generative_ai": "Gen AI",
#             "machine_learning": "ML",
#             "finance_in_tech": "FinTec"
#         })
        
#         st.markdown("#### Filtered Articles")
#         # Display a DataFrame without the hidden fields.
#         df_reset = df_display_renamed.drop(columns=["url", "summary"]).reset_index(drop=True)
#         st.dataframe(df_reset, height=500)
#     st.markdown("---")
        
#     col3, col6, col7 = st.columns([1, 2, 2,])
#     with col3:
#         # --- Article Selection Section ---
#         st.markdown("#### Article Selection")
#         # --- Row Selection ---
#         selected_title = st.selectbox("Select an Article (by title)", df_display_renamed["Title"].unique())
#         selected_article = df_db[df_db["Title"] == selected_title].iloc[0]

        
#         #st.write("**Title:**", selected_article["Title"])
#         st.write("**Source:**", selected_article["source"])
#         st.write("**Released on:**", selected_article["timestamp"])
#         # Display the article text.
#         #st.markdown("**Article Content:**")
#         st.markdown("#### Select Output Form")
#         form_choice = st.radio("Choose your output destination:", options=["LinkedIn", "Newsletter"])
#         if form_choice == "Newsletter":
#             specific_choice = st.radio("Select Newsletter frequency:", options=["Weekly", "Monthly"])
#         elif form_choice == "LinkedIn":
#             specific_choice = st.radio("Select LinkedIn post type:", options=[
#                 "New post", "Carousel", "Commercial post", "Erik's self branding"
#             ])
   
#     with col6:
#         st.text_area("Full Article Text", selected_article["text"], height=800)
#         article_url = selected_article["url"]
#         article_text = get_article_text(article_url)
#         if not article_text:
#             st.error("Failed to retrieve article content.")
#         else:
#             if st.button("Confirm Choices"):
#                 # Initialize conversation thread if it doesn't exist
#                 # Note: Using only user and assistant roles, no system role
#                 if "conversation_thread" not in st.session_state:
#                     st.session_state.conversation_thread = []
                
#                 # Initialize content versions if it doesn't exist
#                 if "content_versions" not in st.session_state:
#                     st.session_state.content_versions = []
                
#                 prompt_key = (form_choice, specific_choice)
#                 if prompt_key not in prompt_dict:
#                     st.error("No prompt defined for this combination.")
#                 else:
#                     prompt_text = prompt_dict[prompt_key]
#                     # Add instructional prefix to make up for lack of system message
#                     full_prompt = f"You are a marketing content expert helping create and refine content based on articles. {prompt_text}\n\nArticle content:\n{article_text}"
                    
#                     # Add user prompt to conversation thread
#                     st.session_state.conversation_thread.append(
#                         {"role": "user", "content": full_prompt}
#                     )
                    
#                     st.info("Calling the language model for content generation...")
#                     try:
#                         client = OpenAI()
#                         response = client.chat.completions.create(
#                             model="o1-mini",
#                             messages=st.session_state.conversation_thread,
#                             max_completion_tokens=5000
#                             #temperature=1
#                         )
#                         llm_output = response.choices[0].message.content.strip()
                        
#                         # Add assistant response to conversation thread
#                         st.session_state.conversation_thread.append(
#                             {"role": "assistant", "content": llm_output}
#                         )
                        
#                         # Store the content in session state
#                         st.session_state.llm_output = llm_output
                        
#                         # Add to content versions
#                         st.session_state.content_versions.append({
#                             "version": 1,
#                             "content": llm_output,
#                             "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
#                             "description": "Initial generation"
#                         })
                        
#                         # Set current version index
#                         st.session_state.current_version_index = 0
                        
#                     except Exception as e:
#                         st.error(f"Error during LLM call: {e}")    

#     with col7:
#         if "llm_output" in st.session_state:
#             # Create tabs for content and history
#             content_tab, history_tab = st.tabs(["Content", "Version History"])
            
#             with content_tab:
#                 # Get the current content
#                 current_content = st.session_state.llm_output
#                 if "edited_content" in st.session_state:
#                     current_content = st.session_state.edited_content
                
#                 # Display editable text area
#                 edited_content = st.text_area(
#                     f"LLM Output for {form_choice} {specific_choice}", 
#                     current_content, 
#                     height=500
#                 )
                
#                 # Update edited content in session state if changed
#                 if edited_content != current_content:
#                     st.session_state.edited_content = edited_content
                
#                 # Conversation interface
#                 st.markdown("### How would you like to improve this content?")
                
#                 # Initialize refinement history if it doesn't exist
#                 if "refinement_history" not in st.session_state:
#                     st.session_state.refinement_history = []
                
#                 # Display refinement history
#                 for i, exchange in enumerate(st.session_state.refinement_history):
#                     with st.expander(f"Refinement {i+1}: {exchange['instruction'][:50]}...", expanded=False):
#                         st.markdown(f"**Your instruction:**\n{exchange['instruction']}")
#                         st.markdown(f"**AI response:**\n{exchange['response']}")
                
#                 # Input for new refinement - use a unique key based on the number of refinements
#                 # This naturally creates a new widget each time, avoiding the need to clear it
#                 refinement_key = f"refinement_instruction_{len(st.session_state.refinement_history)}"
#                 user_instruction = st.text_input("Enter your instruction:", key=refinement_key)
                
#                 if st.button("Apply Changes", key=f"apply_changes_{len(st.session_state.refinement_history)}"):
#                     if user_instruction:
#                         # Get current content (either edited or original)
#                         current_content = edited_content if "edited_content" in st.session_state else st.session_state.llm_output
                        
#                         # Add user instruction to conversation thread
#                         st.session_state.conversation_thread.append(
#                             {"role": "user", "content": f"Here is the current content:\n\n{current_content}\n\nInstruction: {user_instruction}"}
#                         )
                        
#                         with st.spinner("Processing your request..."):
#                             try:
#                                 # Call OpenAI with the full conversation history
#                                 client = OpenAI()
#                                 response = client.chat.completions.create(
#                                     model="o1-mini",
#                                     messages=st.session_state.conversation_thread,
#                                     max_completion_tokens=5000
#                                     #temperature=0.7
#                                 )
                                
#                                 # Get the refined content
#                                 refined_content = response.choices[0].message.content.strip()
                                
#                                 # Add assistant response to conversation thread
#                                 st.session_state.conversation_thread.append(
#                                     {"role": "assistant", "content": refined_content}
#                                 )
                                
#                                 # Update the output
#                                 st.session_state.llm_output = refined_content
                                
#                                 # Clear edited content
#                                 if "edited_content" in st.session_state:
#                                     del st.session_state.edited_content
                                
#                                 # Add to refinement history
#                                 st.session_state.refinement_history.append({
#                                     "instruction": user_instruction,
#                                     "response": refined_content
#                                 })
                                
#                                 # Add to content versions
#                                 st.session_state.content_versions.append({
#                                     "version": len(st.session_state.content_versions) + 1,
#                                     "content": refined_content,
#                                     "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
#                                     "description": user_instruction[:50] + "..." if len(user_instruction) > 50 else user_instruction
#                                 })
                                
#                                 # Update current version index
#                                 st.session_state.current_version_index = len(st.session_state.content_versions) - 1
                                
#                                 st.success("Content updated successfully!")
#                                 st.rerun()
                                
#                             except Exception as e:
#                                 st.error(f"Error during refinement: {e}")
                            
#                             # Button to review edits
#                             if "edited_content" in st.session_state and st.session_state.edited_content != st.session_state.llm_output:
#                                 if st.button("Review My Edits"):
#                                     with st.spinner("Analyzing your edits..."):
#                                         try:
#                                             # Create a prompt for reviewing edits (without system role)
#                                             review_prompt = [
#                                                 {"role": "user", "content": f"You are a marketing content expert helping review edits. Original content:\n\n{st.session_state.llm_output}\n\nEdited content:\n\n{st.session_state.edited_content}\n\nPlease review these edits and provide feedback on the changes made. Are they good changes? What improved and what might need further attention?"}
#                                             ]
                                            
#                                             # Call OpenAI for review
#                                             client = OpenAI()
#                                             response = client.chat.completions.create(
#                                                 model="o1-mini",
#                                                 messages=review_prompt,
#                                                 max_completion_tokens=2000
#                                                 #temperature=0.5
#                                             )
                                            
#                                             # Display the review
#                                             review_result = response.choices[0].message.content.strip()
#                                             st.session_state.edit_review = review_result
                                            
#                                         except Exception as e:
#                                             st.error(f"Error during edit review: {e}")
                
#                 # Display edit review if available
#                 if "edit_review" in st.session_state:
#                     with st.expander("Edit Review", expanded=True):
#                         st.markdown(st.session_state.edit_review)
            
#             with history_tab:
#                 st.markdown("### Version History")
                
#                 if "content_versions" in st.session_state and st.session_state.content_versions:
#                     # Create a DataFrame of versions for display
#                     versions_df = pd.DataFrame([
#                         {
#                             "Version": v["version"],
#                             "Timestamp": v["timestamp"],
#                             "Description": v["description"],
#                         } for v in st.session_state.content_versions
#                     ])
                    
#                     # Display versions table
#                     st.dataframe(versions_df)
                    
#                     # Version selection
#                     selected_version = st.selectbox(
#                         "Select a version to view or restore:",
#                         range(len(st.session_state.content_versions)),
#                         format_func=lambda i: f"V{st.session_state.content_versions[i]['version']}: {st.session_state.content_versions[i]['description'][:30]}...",
#                         index=st.session_state.current_version_index
#                     )
                    
#                     # Show selected version content
#                     st.text_area(
#                         "Version Content", 
#                         st.session_state.content_versions[selected_version]["content"],
#                         height=300
#                     )
                    
#                     # Restore button
#                     if selected_version != st.session_state.current_version_index:
#                         if st.button("Restore This Version"):
#                             # Update current content
#                             st.session_state.llm_output = st.session_state.content_versions[selected_version]["content"]
                            
#                             # Update current version index
#                             st.session_state.current_version_index = selected_version
                            
#                             # Clear edited content
#                             if "edited_content" in st.session_state:
#                                 del st.session_state.edited_content
                            
#                             st.success(f"Restored to version {st.session_state.content_versions[selected_version]['version']}")
#                             st.rerun()
#                 else:
#                     st.info("No version history available yet.")

def content_creation_section():
    st.markdown("# Content Creation")
    col1, col2 = st.columns([1, 2])
    
    with col1:
        # Retrieve articles from DynamoDB
        response = table.scan()
        articles = response.get('Items', [])
        
        if not articles:
            st.error("No articles found in the database. Please build and persist your knowledge base.")
            return
        
        df_db = pd.DataFrame(articles)
        
        # Convert timestamp string to datetime for filtering
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
        # Display Filtered Articles with Renamed Columns
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
        # Display a DataFrame without the hidden fields
        df_reset = df_display_renamed.drop(columns=["url", "summary"]).reset_index(drop=True)
        
        # Using Streamlit's native row selection feature
        selection = st.dataframe(
            df_reset,
            height=500,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Title": st.column_config.TextColumn("Title", width="large"),
                "Source": st.column_config.TextColumn("Source", width="small"),
                "Released on": st.column_config.TextColumn("Released on", width="medium"),
                "Dig Transf": st.column_config.NumberColumn("Dig Transf", width="small"),
                "Gen AI": st.column_config.NumberColumn("Gen AI", width="small"),
                "ML": st.column_config.NumberColumn("ML", width="small"),
                "FinTec": st.column_config.NumberColumn("FinTec", width="small")
            },
            on_select="rerun",  # Rerun the app when a selection is made
            selection_mode="single-row"  # Allow only one row to be selected at a time
        )
    st.markdown("---")

    col3, col4, col5 = st.columns([1, 1, 1])

    with col3:
        # Article Selection Section
        st.markdown("#### Article Selection")
        
        # Check if a row is selected
        if selection.selection and hasattr(selection.selection, 'rows') and len(selection.selection.rows) > 0:
            # Get the index of the selected row
            selected_row_index = selection.selection.rows[0]
            # Get the title of the selected article
            selected_article_title = df_reset.iloc[selected_row_index]["Title"]
            # Find the selected article in the original dataframe
            selected_article = df_db[df_db["Title"] == selected_article_title].iloc[0]
            
            # Show success message
            st.success(f"Selected: {selected_article_title}")
            st.write("**Source:**", selected_article["source"])
            st.write("**Released on:**", selected_article["timestamp"])
        else:
            # If no row is selected, just show a message
            st.warning("Select an article by clicking on a row in the table above")
            return  # Exit the function early
        
        with col4:
            st.markdown("#### Select Output Form")
            # Display the article text
        
            form_choice = st.radio("Choose your output destination:", options=["LinkedIn", "Newsletter"])
            if form_choice == "Newsletter":
                specific_choice = st.radio("Select Newsletter frequency:", options=["Weekly", "Monthly"])
            elif form_choice == "LinkedIn":
                specific_choice = st.radio("Select LinkedIn post type:", options=[
                    "New post", "Carousel", "Commercial post", "Erik's self branding"
                ])

    
    st.markdown("---")
    st.markdown("#### Content Elaboration")
        
    # col3, col6, col7 = st.columns([1, 2, 2])
    # with col3:
    #     # Article Selection Section
    #     st.markdown("#### Article Selection")
        
    #     # Check if a row is selected
    #     if selection.selection and hasattr(selection.selection, 'rows') and len(selection.selection.rows) > 0:
    #         # Get the index of the selected row
    #         selected_row_index = selection.selection.rows[0]
    #         # Get the title of the selected article
    #         selected_article_title = df_reset.iloc[selected_row_index]["Title"]
    #         # Find the selected article in the original dataframe
    #         selected_article = df_db[df_db["Title"] == selected_article_title].iloc[0]
            
    #         # Show success message
    #         st.success(f"Selected: {selected_article_title}")
    #     else:
    #         # Fallback to dropdown selection if no row is selected
    #         st.info("Select an article by clicking on a row in the table above, or use the dropdown below:")
    #         selected_title = st.selectbox("Select an Article (by title)", df_display_renamed["Title"].unique())
    #         selected_article = df_db[df_db["Title"] == selected_title].iloc[0]
        
    #     st.write("**Source:**", selected_article["source"])
    #     st.write("**Released on:**", selected_article["timestamp"])
        
    #     # Display the article text
    #     st.markdown("#### Select Output Form")
    #     form_choice = st.radio("Choose your output destination:", options=["LinkedIn", "Newsletter"])
    #     if form_choice == "Newsletter":
    #         specific_choice = st.radio("Select Newsletter frequency:", options=["Weekly", "Monthly"])
    #     elif form_choice == "LinkedIn":
    #         specific_choice = st.radio("Select LinkedIn post type:", options=[
    #             "New post", "Carousel", "Commercial post", "Erik's self branding"
    #         ])
    col6, col7 = st.columns([1, 1])    
    with col6:
        st.text_area("Full Article Text", selected_article["text"], height=800)
        article_url = selected_article["url"]
        article_text = get_article_text(article_url)
        if not article_text:
            st.error("Failed to retrieve article content.")
        else:
            if st.button("Confirm Choices"):
                # Initialize conversation thread if it doesn't exist
                if "conversation_thread" not in st.session_state:
                    st.session_state.conversation_thread = []
                
                # Initialize content versions if it doesn't exist
                if "content_versions" not in st.session_state:
                    st.session_state.content_versions = []
                
                prompt_key = (form_choice, specific_choice)
                if prompt_key not in prompt_dict:
                    st.error("No prompt defined for this combination.")
                else:
                    prompt_text = prompt_dict[prompt_key]
                    # Add instructional prefix to make up for lack of system message
                    full_prompt = f"You are a marketing content expert helping create and refine content based on articles. {prompt_text}\n\nArticle content:\n{article_text}"
                    
                    # Add user prompt to conversation thread
                    st.session_state.conversation_thread.append(
                        {"role": "user", "content": full_prompt}
                    )
                    
                    st.info("Calling the language model for content generation...")
                    try:
                        client = OpenAI()
                        response = client.chat.completions.create(
                            model="o1-mini",
                            messages=st.session_state.conversation_thread,
                            max_completion_tokens=5000
                        )
                        llm_output = response.choices[0].message.content.strip()
                        
                        # Add assistant response to conversation thread
                        st.session_state.conversation_thread.append(
                            {"role": "assistant", "content": llm_output}
                        )
                        
                        # Store the content in session state
                        st.session_state.llm_output = llm_output
                        
                        # Add to content versions
                        st.session_state.content_versions.append({
                            "version": 1,
                            "content": llm_output,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "description": "Initial generation"
                        })
                        
                        # Set current version index
                        st.session_state.current_version_index = 0
                        
                    except Exception as e:
                        st.error(f"Error during LLM call: {e}")    

    with col7:
        if "llm_output" in st.session_state:
            # Create tabs for content and history
            content_tab, history_tab = st.tabs(["Content", "Version History"])
            
            with content_tab:
                # Get the current content
                current_content = st.session_state.llm_output
                if "edited_content" in st.session_state:
                    current_content = st.session_state.edited_content
                
                # Display editable text area
                edited_content = st.text_area(
                    f"LLM Output for {form_choice} {specific_choice}", 
                    current_content, 
                    height=500
                )
                
                # Update edited content in session state if changed
                if edited_content != current_content:
                    st.session_state.edited_content = edited_content
                
                # Conversation interface
                st.markdown("### How would you like to improve this content?")
                
                # Initialize refinement history if it doesn't exist
                if "refinement_history" not in st.session_state:
                    st.session_state.refinement_history = []
                
                # Display refinement history
                for i, exchange in enumerate(st.session_state.refinement_history):
                    with st.expander(f"Refinement {i+1}: {exchange['instruction'][:50]}...", expanded=False):
                        st.markdown(f"**Your instruction:**\n{exchange['instruction']}")
                        st.markdown(f"**AI response:**\n{exchange['response']}")
                
                # Input for new refinement - use a unique key based on the number of refinements
                refinement_key = f"refinement_instruction_{len(st.session_state.refinement_history)}"
                user_instruction = st.text_input("Enter your instruction:", key=refinement_key)
                
                if st.button("Apply Changes", key=f"apply_changes_{len(st.session_state.refinement_history)}"):
                    if user_instruction:
                        # Get current content (either edited or original)
                        current_content = edited_content if "edited_content" in st.session_state else st.session_state.llm_output
                        
                        # Add user instruction to conversation thread
                        st.session_state.conversation_thread.append(
                            {"role": "user", "content": f"Here is the current content:\n\n{current_content}\n\nInstruction: {user_instruction}"}
                        )
                        
                        with st.spinner("Processing your request..."):
                            try:
                                # Call OpenAI with the full conversation history
                                client = OpenAI()
                                response = client.chat.completions.create(
                                    model="o1-mini",
                                    messages=st.session_state.conversation_thread,
                                    max_completion_tokens=5000
                                )
                                
                                # Get the refined content
                                refined_content = response.choices[0].message.content.strip()
                                
                                # Add assistant response to conversation thread
                                st.session_state.conversation_thread.append(
                                    {"role": "assistant", "content": refined_content}
                                )
                                
                                # Update the output
                                st.session_state.llm_output = refined_content
                                
                                # Clear edited content
                                if "edited_content" in st.session_state:
                                    del st.session_state.edited_content
                                
                                # Add to refinement history
                                st.session_state.refinement_history.append({
                                    "instruction": user_instruction,
                                    "response": refined_content
                                })
                                
                                # Add to content versions
                                st.session_state.content_versions.append({
                                    "version": len(st.session_state.content_versions) + 1,
                                    "content": refined_content,
                                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "description": user_instruction[:50] + "..." if len(user_instruction) > 50 else user_instruction
                                })
                                
                                # Update current version index
                                st.session_state.current_version_index = len(st.session_state.content_versions) - 1
                                
                                st.success("Content updated successfully!")
                                st.rerun()
                                
                            except Exception as e:
                                st.error(f"Error during refinement: {e}")
                
                # Button to review edits
                if "edited_content" in st.session_state and st.session_state.edited_content != st.session_state.llm_output:
                    if st.button("Review My Edits"):
                        with st.spinner("Analyzing your edits..."):
                            try:
                                # Create a prompt for reviewing edits (without system role)
                                review_prompt = [
                                    {"role": "user", "content": f"You are a marketing content expert helping review edits. Original content:\n\n{st.session_state.llm_output}\n\nEdited content:\n\n{st.session_state.edited_content}\n\nPlease review these edits and provide feedback on the changes made. Are they good changes? What improved and what might need further attention?"}
                                ]
                                
                                # Call OpenAI for review
                                client = OpenAI()
                                response = client.chat.completions.create(
                                    model="o1-mini",
                                    messages=review_prompt,
                                    max_completion_tokens=2000
                                )
                                
                                # Display the review
                                review_result = response.choices[0].message.content.strip()
                                st.session_state.edit_review = review_result
                                
                            except Exception as e:
                                st.error(f"Error during edit review: {e}")
                
                # Display edit review if available
                if "edit_review" in st.session_state:
                    with st.expander("Edit Review", expanded=True):
                        st.markdown(st.session_state.edit_review)
            
            with history_tab:
                st.markdown("### Version History")
                
                if "content_versions" in st.session_state and st.session_state.content_versions:
                    # Create a DataFrame of versions for display
                    versions_df = pd.DataFrame([
                        {
                            "Version": v["version"],
                            "Timestamp": v["timestamp"],
                            "Description": v["description"],
                        } for v in st.session_state.content_versions
                    ])
                    
                    # Display versions table
                    st.dataframe(versions_df)
                    
                    # Version selection
                    selected_version = st.selectbox(
                        "Select a version to view or restore:",
                        range(len(st.session_state.content_versions)),
                        format_func=lambda i: f"V{st.session_state.content_versions[i]['version']}: {st.session_state.content_versions[i]['description'][:30]}...",
                        index=st.session_state.current_version_index
                    )
                    
                    # Show selected version content
                    st.text_area(
                        "Version Content", 
                        st.session_state.content_versions[selected_version]["content"],
                        height=300
                    )
                    
                    # Restore button
                    if selected_version != st.session_state.current_version_index:
                        if st.button("Restore This Version"):
                            # Update current content
                            st.session_state.llm_output = st.session_state.content_versions[selected_version]["content"]
                            
                            # Update current version index
                            st.session_state.current_version_index = selected_version
                            
                            # Clear edited content
                            if "edited_content" in st.session_state:
                                del st.session_state.edited_content
                            
                            st.success(f"Restored to version {st.session_state.content_versions[selected_version]['version']}")
                            st.rerun()
                else:
                    st.info("No version history available yet.")

def app():
    st.title("MarketingMate")
    
    # Add AWS Credentials Check
    if verify_aws_credentials() and table is not None:
        database_management_section()
        st.markdown("---")
        content_creation_section()
    else:
        st.error("Please configure AWS credentials and ensure DynamoDB table exists.")

if __name__ == "__main__":
    app()
