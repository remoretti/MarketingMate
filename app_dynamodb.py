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
from date_utils import parse_rss_date

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
def filter_articles_by_date(articles_list, days_back=7):
    """
    Filter articles to only include those from the last N days.
    Fixed timezone handling to avoid comparison errors.
    
    Args:
        articles_list: List of article dictionaries
        days_back: Number of days to look back (default: 7)
    
    Returns:
        Filtered list of recent articles
    """
    from datetime import datetime, timedelta
    import pandas as pd
    
    if not articles_list:
        return []
    
    # Calculate cutoff date (UTC, timezone-naive)
    cutoff_date = datetime.utcnow() - timedelta(days=days_back)
    
    filtered_articles = []
    total_articles = len(articles_list)
    skipped_articles = 0
    
    print(f"🗓️ Filtering articles newer than: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    
    for article in articles_list:
        try:
            # Parse the article date
            article_date_str = article.get('Date Created', '')
            if not article_date_str or article_date_str == 'No Date':
                skipped_articles += 1
                continue
            
            # Parse with pandas (handles various formats)
            article_date = pd.to_datetime(article_date_str, utc=True)
            
            # Convert to naive datetime in UTC for comparison
            if article_date.tzinfo is not None:
                article_date_naive = article_date.tz_convert('UTC').tz_localize(None)
            else:
                article_date_naive = article_date
            
            # Compare with cutoff (both now timezone-naive UTC)
            if article_date_naive >= cutoff_date:
                filtered_articles.append(article)
                
        except Exception as e:
            # If date parsing fails, skip the article
            print(f"⚠️ Date parsing error for article '{article.get('Title', 'Unknown')[:50]}...': {e}")
            skipped_articles += 1
            continue
    
    filtered_count = len(filtered_articles)
    
    print(f"📅 Date Filter Results:")
    print(f"   📄 Total articles: {total_articles}")
    print(f"   📅 Articles from last {days_back} days: {filtered_count}")
    print(f"   ⚠️ Skipped articles (date issues): {skipped_articles}")
    if total_articles > 0:
        print(f"   💰 Cost reduction: {((total_articles - filtered_count) / total_articles * 100):.1f}%")
    
    # Show sample of recent articles found
    if filtered_articles:
        print(f"✅ Sample recent articles:")
        for i, article in enumerate(filtered_articles[:3]):
            print(f"   {i+1}. {article.get('Date Created', 'No Date')} - {article.get('Title', 'No Title')[:60]}...")
    
    return filtered_articles


def get_all_articles():
    """Get all articles from DynamoDB with pagination support."""
    articles = []
    last_evaluated_key = None
    
    while True:
        if last_evaluated_key:
            response = table.scan(ExclusiveStartKey=last_evaluated_key)
        else:
            response = table.scan()
        
        articles.extend(response.get('Items', []))
        
        last_evaluated_key = response.get('LastEvaluatedKey')
        if not last_evaluated_key:
            break
    
    return articles

def display_recent_update():
    """Display the most recent article's timestamp with proper pagination."""
    try:
        # Initialize variables to track the most recent timestamp
        most_recent_article = None
        most_recent_timestamp = None
        
        # Use pagination to scan through all items
        last_evaluated_key = None
        while True:
            # Perform scan with pagination
            if last_evaluated_key:
                response = table.scan(ExclusiveStartKey=last_evaluated_key)
            else:
                response = table.scan()
            
            articles = response.get('Items', [])
            
            # Process this batch of articles
            if articles:
                for article in articles:
                    if 'timestamp' in article:
                        # Parse the timestamp
                        try:
                            article_timestamp = pd.to_datetime(article['timestamp'])
                            
                            # Check if this is the most recent
                            if most_recent_timestamp is None or article_timestamp > most_recent_timestamp:
                                most_recent_timestamp = article_timestamp
                                most_recent_article = article
                        except:
                            # Skip articles with unparseable timestamps
                            continue
            
            # Check if there are more items to scan
            last_evaluated_key = response.get('LastEvaluatedKey')
            if not last_evaluated_key:
                break
        
        # Display the most recent article information
        if most_recent_timestamp:
            st.write(f"Most Recent Article Released On: {most_recent_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
            st.write(f"Title: {most_recent_article.get('Title', 'Unknown Title')}")
            st.write(f"Source: {most_recent_article.get('source', 'Unknown Source')}")
        else:
            st.write("No articles found with valid timestamps.")
    
    except Exception as e:
        st.error(f"Error fetching recent update: {e}")
        st.error(f"Details: {traceback.format_exc()}")

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
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

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
    try:
        article_url = row["URL"]
        
        # Validate URL
        if not article_url or article_url == 'No URL':
            st.error(f"Invalid URL for article: {row.get('Title', 'Unknown')}")
            return None
        
        article_text = get_article_text(article_url)
        if not article_text:
            st.warning(f"No content retrieved for: {row.get('Title', 'Unknown')}")
            return None  # Skip if content retrieval fails.
        
        # Use the standardized date that's already been processed in fetch_feed
        timestamp = row["Date Created"]
        
        state_input: ArticleState = {
            "text": article_text,
            "ranking": {},
            "timestamp": timestamp,
            "summary": row["Summary"],
            "source": row["RSS Source"]
        }
        
        # Process with LangGraph agent
        result_state = agent.invoke(state_input)
        
        # Validate that we have a result
        if not result_state:
            st.error(f"LangGraph agent returned empty result for: {row.get('Title', 'Unknown')}")
            return None
        
        # Add the URL and Title for later persistence.
        result_state["url"] = article_url
        result_state["Title"] = row["Title"]  # Ensure the Title field is stored.
        
        # Transform the ranking into separate properties.
        ranking = result_state.get("ranking", {})
        if isinstance(ranking, str):
            try:
                ranking = json.loads(ranking)
            except Exception as e:
                st.warning(f"Failed to parse ranking JSON for {row.get('Title', 'Unknown')}: {e}")
                ranking = {}
        
        # Ensure ranking values are integers
        result_state["digital_transformation"] = int(ranking.get("Digital Transformation", 0))
        result_state["generative_ai"] = int(ranking.get("Generative AI", 0))
        result_state["machine_learning"] = int(ranking.get("Machine Learning / Data Science", 0))
        result_state["finance_in_tech"] = int(ranking.get("Finance in tech", 0))
        
        # Validate final result
        required_fields = ["url", "Title", "timestamp", "source", "text"]
        for field in required_fields:
            if field not in result_state or result_state[field] is None:
                st.error(f"Missing required field '{field}' for article: {row.get('Title', 'Unknown')}")
                return None
        
        return result_state
        
    except Exception as e:
        st.error(f"Error processing article '{row.get('Title', 'Unknown')}': {e}")
        st.error(f"Error details: {traceback.format_exc()}")
        return None


def debug_dynamodb_connection():
    """Debug function to test DynamoDB connection and table access."""
    st.write("🔍 Debugging DynamoDB Connection...")
    
    try:
        # Test basic table access using the client, not the table resource
        dynamodb_client = boto3.client(
            'dynamodb', 
            region_name=os.getenv('AWS_DEFAULT_REGION', 'us-east-1'),
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
        )
        
        # Get table description using client
        response = dynamodb_client.describe_table(TableName='MarketingMateDB')
        st.success("✅ Successfully connected to DynamoDB table")
        st.write(f"Table Name: {response['Table']['TableName']}")
        st.write(f"Table Status: {response['Table']['TableStatus']}")
        st.write(f"Item Count: {response['Table']['ItemCount']}")
        
        # Test read permissions with table resource
        st.write("🔍 Testing read permissions...")
        scan_response = table.scan(Limit=1)
        st.success(f"✅ Read test successful - found {scan_response['Count']} items")
        
        # Test write permissions by writing a simple test item
        st.write("🔍 Testing write permissions...")
        test_item = {
            'url': f'test-url-{int(datetime.utcnow().timestamp())}',
            'Title': 'Test Article for Debug',
            'timestamp': datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
            'source': 'Debug Test',
            'text': 'Test text content for debugging',
            'digital_transformation': 5,
            'generative_ai': 3,
            'machine_learning': 2,
            'finance_in_tech': 1,
            'summary': 'Test summary'
        }
        
        # Try to write test item
        table.put_item(Item=test_item)
        st.success("✅ Successfully wrote test item to DynamoDB")
        
        # Try to read it back
        get_response = table.get_item(Key={'url': test_item['url']})
        if 'Item' in get_response:
            st.success("✅ Successfully read test item back from DynamoDB")
            
            # Clean up test item
            table.delete_item(Key={'url': test_item['url']})
            st.success("✅ Successfully deleted test item")
            
            # Final verification
            get_response_after_delete = table.get_item(Key={'url': test_item['url']})
            if 'Item' not in get_response_after_delete:
                st.success("✅ Test item successfully removed - all operations working!")
            else:
                st.warning("⚠️ Test item still exists after deletion attempt")
        else:
            st.error("❌ Could not read test item back from database")
            
    except Exception as e:
        st.error(f"❌ DynamoDB connection error: {e}")
        st.error(f"Full error: {traceback.format_exc()}")
        
        # Additional AWS credentials debugging
        st.write("🔍 Checking AWS credentials...")
        try:
            sts_client = boto3.client('sts',
                region_name=os.getenv('AWS_DEFAULT_REGION', 'us-east-1'),
                aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
            )
            identity = sts_client.get_caller_identity()
            st.write(f"AWS Account: {identity.get('Account', 'Unknown')}")
            st.write(f"AWS User/Role: {identity.get('Arn', 'Unknown')}")
        except Exception as cred_error:
            st.error(f"AWS Credentials Error: {cred_error}")

# Also add this simpler connection test
def test_simple_write():
    """Simple write test to isolate the issue."""
    st.write("🔍 Testing Simple Write Operation...")
    
    try:
        # Create a very simple test item
        simple_item = {
            'url': 'simple-test-123',
            'Title': 'Simple Test'
        }
        
        # Test put_item
        table.put_item(Item=simple_item)
        st.success("✅ Simple write successful")
        
        # Test get_item
        response = table.get_item(Key={'url': 'simple-test-123'})
        if 'Item' in response:
            st.success("✅ Simple read successful")
            
            # Clean up
            table.delete_item(Key={'url': 'simple-test-123'})
            st.success("✅ Simple delete successful")
        else:
            st.error("❌ Simple read failed")
            
    except Exception as e:
        st.error(f"❌ Simple write test failed: {e}")
        st.error(f"Error type: {type(e).__name__}")
        st.error(f"Full error: {traceback.format_exc()}")

def debug_article_save(knowledge_base):
    """Debug the actual article saving process."""
    st.write("🔍 Debugging Article Save Process...")
    
    if not knowledge_base:
        st.error("No knowledge base provided for debugging")
        return
    
    st.write(f"📊 Articles to save: {len(knowledge_base)}")
    
    # Debug first article structure
    first_article = knowledge_base[0]
    st.write("🔍 First article structure:")
    st.json(first_article)
    
    # Check for problematic data types
    st.write("🔍 Checking data types in first article:")
    for key, value in first_article.items():
        value_type = type(value).__name__
        st.write(f"- {key}: {value_type}")
        
        # Check for problematic types
        if value_type in ['dict', 'list', 'NoneType']:
            st.warning(f"⚠️ Potential issue: {key} has type {value_type}")
            st.write(f"  Value: {value}")
    
    # Test saving just the first article
    st.write("🔍 Testing save of first article only...")
    try:
        # Clean the article
        cleaned_article = {}
        for key, value in first_article.items():
            if value is not None:
                if isinstance(value, dict):
                    cleaned_article[key] = json.dumps(value)
                elif isinstance(value, list):
                    cleaned_article[key] = json.dumps(value)
                else:
                    cleaned_article[key] = str(value) if not isinstance(value, (int, float, bool, str)) else value
            else:
                st.warning(f"Skipping None value for key: {key}")
        
        # Add TTL
        cleaned_article['ttl'] = int(datetime.utcnow().timestamp()) + (180 * 24 * 60 * 60)
        
        st.write("🔍 Cleaned article structure:")
        st.json(cleaned_article)
        
        # Try to save
        table.put_item(Item=cleaned_article)
        st.success("✅ First article saved successfully!")
        
        # Verify it exists
        url_to_check = cleaned_article['url']
        get_response = table.get_item(Key={'url': url_to_check})
        if 'Item' in get_response:
            st.success("✅ First article verified in database!")
            
            # Check total count after save
            articles = get_all_articles()
            new_count = len(articles)
            st.write(f"📊 Total articles after test save: {new_count}")
            
        else:
            st.error("❌ First article not found after save")
            
    except Exception as e:
        st.error(f"❌ Failed to save first article: {e}")
        st.error(f"Error type: {type(e).__name__}")
        st.error(f"Full error: {traceback.format_exc()}")

def debug_batch_save(knowledge_base):
    """Debug the batch save process specifically."""
    st.write("🔍 Debugging Batch Save Process...")
    
    if not knowledge_base:
        st.error("No knowledge base provided")
        return
    
    try:
        st.write(f"📊 Attempting to save {len(knowledge_base)} articles using batch writer...")
        
        with table.batch_writer() as batch:
            for i, article in enumerate(knowledge_base):
                try:
                    # Clean the article data
                    cleaned_article = {}
                    for key, value in article.items():
                        if value is not None:
                            if isinstance(value, dict):
                                cleaned_article[key] = json.dumps(value)
                            elif isinstance(value, list):
                                cleaned_article[key] = json.dumps(value)
                            else:
                                cleaned_article[key] = str(value) if not isinstance(value, (int, float, bool, str)) else value
                    
                    # Add TTL
                    cleaned_article['ttl'] = int(datetime.utcnow().timestamp()) + (180 * 24 * 60 * 60)
                    
                    # Add to batch
                    batch.put_item(Item=cleaned_article)
                    
                    if i < 3:  # Show progress for first 3
                        st.write(f"✅ Added article {i+1} to batch: {cleaned_article.get('Title', 'Unknown')}")
                
                except Exception as item_error:
                    st.error(f"❌ Error adding article {i+1} to batch: {item_error}")
        
        st.success("✅ Batch write completed!")
        
        # Verify by checking count
        articles = get_all_articles()
        new_count = len(articles)
        st.write(f"📊 Total articles after batch save: {new_count}")
        
    except Exception as e:
        st.error(f"❌ Batch save failed: {e}")
        st.error(f"Full error: {traceback.format_exc()}")

# Add this simple save test
def test_save_processed_articles():
    """Test saving the currently processed articles."""
    if 'knowledge_base' not in st.session_state or not st.session_state.knowledge_base:
        st.error("No processed articles found in session state")
        return
    
    knowledge_base = st.session_state.knowledge_base
    st.write(f"🔍 Found {len(knowledge_base)} processed articles in session state")
    
    # Show first few article titles
    st.write("📝 Article titles:")
    for i, article in enumerate(knowledge_base[:5]):
        st.write(f"{i+1}. {article.get('Title', 'No Title')}")
    
    if len(knowledge_base) > 5:
        st.write(f"... and {len(knowledge_base) - 5} more")
    
    # Debug first article
    debug_article_save(knowledge_base)
    
    # Test batch save
    if st.button("🔄 Try Batch Save"):
        debug_batch_save(knowledge_base)


def persist_knowledge_base_dynamodb(knowledge_base):
    """Save articles to DynamoDB with proper data cleaning."""
    if not knowledge_base:
        st.error("No knowledge base to persist.")
        return False
    
    st.info(f"Saving {len(knowledge_base)} articles to DynamoDB...")
    
    try:
        saved_count = 0
        failed_count = 0
        
        # Save articles one by one (more reliable than batch for debugging)
        for i, article in enumerate(knowledge_base):
            try:
                # Clean the article data - same as debug function that worked
                cleaned_article = {}
                for key, value in article.items():
                    if value is not None:
                        if isinstance(value, dict):
                            cleaned_article[key] = json.dumps(value)
                        elif isinstance(value, list):
                            cleaned_article[key] = json.dumps(value)
                        else:
                            cleaned_article[key] = str(value) if not isinstance(value, (int, float, bool, str)) else value
                
                # Add TTL (optional) - expire after 6 months
                cleaned_article['ttl'] = int(datetime.utcnow().timestamp()) + (180 * 24 * 60 * 60)
                
                # Save individual item
                table.put_item(Item=cleaned_article)
                saved_count += 1
                
                # Show progress for first few items
                if i < 5:
                    st.write(f"✅ Saved: {cleaned_article.get('Title', 'Unknown')[:50]}...")
                elif i == 5:
                    st.write(f"... continuing to save remaining {len(knowledge_base) - 5} articles")
                
            except Exception as item_error:
                failed_count += 1
                st.error(f"Failed to save article {i+1}: {item_error}")
        
        # Report results
        if saved_count > 0:
            st.success(f"✅ Successfully saved {saved_count} articles to DynamoDB!")
        
        if failed_count > 0:
            st.warning(f"⚠️ Failed to save {failed_count} articles")
        
        # Update session state
        st.session_state.last_updated = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # Clear processed articles after successful save
        if 'new_articles' in st.session_state:
            del st.session_state.new_articles
        if 'knowledge_base' in st.session_state:
            del st.session_state.knowledge_base
        
        # Force refresh to show updated data
        st.rerun()
        
        return saved_count > 0
        
    except Exception as e:
        st.error(f"Critical error during database save: {e}")
        st.error(f"Full error details: {traceback.format_exc()}")
        return False

def fetch_feed(feed_url, source_name):
    """
    Enhanced fetch_feed function with better error handling and timeout.
    Handles all identified date formats from analysis.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; MarketingMate-RSS-Reader/1.0)',
        'Accept': 'application/rss+xml, application/xml, text/xml',
        'Accept-Language': 'en-US,en;q=0.9'
    }
    
    try:
        response = requests.get(feed_url, headers=headers, timeout=20)
        response.raise_for_status()
        content = response.content
    except requests.exceptions.Timeout:
        raise Exception(f"Timeout after 20 seconds")
    except requests.exceptions.RequestException as e:
        raise Exception(f"Request failed: {e}")
    
    try:
        feed = feedparser.parse(content)
        entries = []
        
        if not feed.entries:
            raise Exception("No entries found in feed")
        
        for entry in feed.entries:
            # Extract basic fields with fallbacks
            title = getattr(entry, 'title', 'No Title')
            link = getattr(entry, 'link', 'No URL')
            summary = getattr(entry, 'summary', getattr(entry, 'description', 'No Summary'))
            
            # Enhanced date extraction - try multiple fields
            date_created = 'No Date'
            for date_field in ['published', 'updated', 'pubDate', 'date']:
                if hasattr(entry, date_field):
                    date_created = getattr(entry, date_field)
                    break
            
            # Use enhanced date parsing from updated date_utils.py
            standardized_date = parse_rss_date(date_created)
            
            # Skip entries with invalid URLs
            if link == 'No URL' or not link.startswith('http'):
                continue
            
            # Clean up HTML entities in title and summary
            import html
            title = html.unescape(title)
            summary = html.unescape(summary)
            
            entries.append({
                "RSS Source": source_name,
                "Title": title,
                "URL": link,
                "Summary": summary,
                "Date Created": standardized_date,
                "Original Date": date_created  # Keep for debugging
            })
        
        return entries
        
    except Exception as e:
        raise Exception(f"Parsing failed: {e}")

@st.cache_data(show_spinner=False)
def get_all_feeds():
    """
    Production-ready feed sources - all verified working as of May 22, 2025.
    Total: 12 reliable feeds providing ~700+ articles
    """
    all_entries = []
    
    # TIER 1: Premium AI/Tech News (High frequency, high quality)
    tier1_feeds = {
        "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml": "The Verge AI",
        "https://deepmind.com/blog/feed/basic/": "Google DeepMind", 
        "https://www.blog.google/technology/ai/rss/": "Google AI Blog",
        "https://openai.com/news/rss.xml": "OpenAI News",
        "https://techcrunch.com/feed/": "TechCrunch",
        "http://www.guardian.co.uk/technology/artificialintelligenceai/rss": "The Guardian AI"
    }
    
    # TIER 2: Business & Academic Sources (Lower frequency, higher depth)
    tier2_feeds = {
        "http://feeds.harvardbusiness.org/harvardbusiness/": "Harvard Business Review",
        "http://feeds.feedburner.com/mitsmr": "MIT Sloan Management Review",
        "https://www.technologyreview.com/feed/": "MIT Technology Review",
        "http://www.sciencedaily.com/rss/computers_math/artificial_intelligence.xml": "ScienceDaily AI"
    }
    
    # TIER 3: General Tech (Mixed content, use relevance filters)
    tier3_feeds = {
        "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml": "New York Times Technology",
        "http://venturebeat.com/feed/": "VentureBeat"
    }
    
    # Process all feeds with detailed logging
    all_feed_sources = {**tier1_feeds, **tier2_feeds, **tier3_feeds}
    
    successful_feeds = 0
    failed_feeds = 0
    
    print(f"🔄 Starting RSS feed collection from {len(all_feed_sources)} sources...")
    
    for url, source_name in all_feed_sources.items():
        try:
            entries = fetch_feed(url, source_name)
            if entries:  # Only add if we got entries
                all_entries.extend(entries)
                successful_feeds += 1
                print(f"✅ {source_name}: {len(entries)} entries")
            else:
                print(f"⚠️ {source_name}: No entries found")
                failed_feeds += 1
        except Exception as e:
            print(f"❌ {source_name}: {str(e)}")
            failed_feeds += 1
            continue
    
    print(f"\n📊 Feed Collection Summary:")
    print(f"   ✅ Successful: {successful_feeds}")
    print(f"   ❌ Failed: {failed_feeds}")
    print(f"   📄 Total articles fetched: {len(all_entries)}")
    
    # Convert to DataFrame and process
    df = pd.DataFrame(all_entries)
    if not df.empty:
        df = df[["RSS Source", "Title", "URL", "Summary", "Date Created"]]
        
        # Sort by date (most recent first)
        try:
            df['Date Created'] = pd.to_datetime(df['Date Created'], errors='coerce')
            df = df.sort_values('Date Created', ascending=False)
            df['Date Created'] = df['Date Created'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        except Exception as e:
            print(f"⚠️ Date sorting error: {e}")
        
        # Remove duplicates by URL (in case feeds overlap)
        original_count = len(df)
        df = df.drop_duplicates(subset=['URL'], keep='first')
        if len(df) < original_count:
            print(f"🔄 Removed {original_count - len(df)} duplicate articles")
        
        print(f"📄 Final article count: {len(df)} unique articles")
    else:
        print("❌ No articles retrieved from any feed")
    
    return df

# ---------------------------
# DATABASE MANAGEMENT SECTION
# ---------------------------
def database_management_section():
    st.markdown("### Database Inspection")
    
    # Count documents in DynamoDB with pagination
    articles = get_all_articles()
    count = len(articles)
    st.write(f"Total documents in DynamoDB: {count}")
    
    display_recent_update()
    if "last_updated" in st.session_state:
        st.write(f"Last updated: {st.session_state.last_updated}")
    
    # # Load RSS feeds if not already loaded
    # if "rss_df" not in st.session_state:
    #     st.session_state.rss_df = get_all_feeds()
    
    # df = st.session_state.rss_df

    # if st.button("Check for New Articles"):
    #     with st.spinner("Checking feeds for new articles..."):
    #         # Initialize list to store new articles (metadata only, no processing yet)
    #         new_articles = []
            
    #         # Check each article in the RSS feed against the database
    #         for idx, row in df.iterrows():
    #             article_url = row["URL"]
                
    #             # Check if the article already exists in DynamoDB using the primary key (url)
    #             try:
    #                 existing_response = table.get_item(Key={'url': article_url})
                    
    #                 # If article doesn't exist, add to the new articles list
    #                 if 'Item' not in existing_response:
    #                     new_articles.append(row)
    #                 else:
    #                     # Article exists, skip it
    #                     continue
                        
    #             except Exception as e:
    #                 st.error(f"Error checking for existing article {article_url}: {e}")
    #                 continue
            
    #         # Store the new articles in session state for later processing
    #         st.session_state.new_articles = new_articles
            
    #         # Show a success message with the count
    #         if new_articles:
    #             st.success(f"Found {len(new_articles)} new articles! Click 'Process and Save' to analyze them.")
                
    #             # Debug: Show sample URLs of new articles
    #             st.write("Sample new article URLs:")
    #             for i, article in enumerate(new_articles[:5]):  # Show first 5
    #                 st.write(f"{i+1}. {article['URL']}")
    #             if len(new_articles) > 5:
    #                 st.write(f"... and {len(new_articles) - 5} more")
    #         else:
    #             st.info("No new articles found.")
    # Load RSS feeds if not already loaded
    if "rss_df" not in st.session_state:
        st.session_state.rss_df = get_all_feeds()
    
    df = st.session_state.rss_df

    # Add date filtering controls
    st.markdown("#### Article Processing Controls")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        days_filter = st.selectbox(
            "Process articles from:",
            [1, 3, 7, 14, 30],
            index=2,  # Default to 7 days
            format_func=lambda x: f"Last {x} day{'s' if x > 1 else ''}"
        )
    
    with col2:
        st.metric("Cost Impact", f"~{days_filter * 5}-{days_filter * 15} articles")

    if st.button("Check for New Articles"):
        with st.spinner("Checking feeds for new articles..."):
            # Initialize list to store new articles (metadata only, no processing yet)
            new_articles = []
            
            # Check each article in the RSS feed against the database
            for idx, row in df.iterrows():
                article_url = row["URL"]
                
                # Check if the article already exists in DynamoDB using the primary key (url)
                try:
                    existing_response = table.get_item(Key={'url': article_url})
                    
                    # If article doesn't exist, add to the new articles list
                    if 'Item' not in existing_response:
                        new_articles.append(row.to_dict())
                    else:
                        # Article exists, skip it
                        continue
                        
                except Exception as e:
                    st.error(f"Error checking for existing article {article_url}: {e}")
                    continue
            
            # Apply date filtering BEFORE processing
            if new_articles:
                # Convert DataFrame rows to the format expected by filter function
                articles_for_filtering = []
                for article in new_articles:
                    articles_for_filtering.append({
                        'Date Created': article['Date Created'],
                        'Title': article['Title'],
                        'URL': article['URL'],
                        'Summary': article['Summary'],
                        'RSS Source': article['RSS Source']
                    })
                
                # Apply date filter
                filtered_articles = filter_articles_by_date(articles_for_filtering, days_back=days_filter)
                
                # Convert back to the format expected by the rest of the app
                st.session_state.new_articles = []
                for filtered_article in filtered_articles:
                    # Find the original row that matches this filtered article
                    for original_article in new_articles:
                        if original_article['URL'] == filtered_article['URL']:
                            st.session_state.new_articles.append(original_article)
                            break
                
                # Show results
                if st.session_state.new_articles:
                    st.success(f"Found {len(st.session_state.new_articles)} recent articles (last {days_filter} days)!")
                    st.info(f"💰 Cost savings: Filtered out {len(new_articles) - len(st.session_state.new_articles)} older articles")
                    
                    # Show sample of what will be processed
                    if len(st.session_state.new_articles) > 0:
                        st.write("📋 Recent articles to process:")
                        sample_df = pd.DataFrame(st.session_state.new_articles[:5])  # Show first 5
                        st.dataframe(sample_df[['RSS Source', 'Title', 'Date Created']])
                        if len(st.session_state.new_articles) > 5:
                            st.write(f"... and {len(st.session_state.new_articles) - 5} more recent articles")
                else:
                    st.info(f"No new articles found from the last {days_filter} days.")
            else:
                st.info("No new articles found.")
    
    # FIXED: Move this outside the button - only show if new articles exist
    if "new_articles" in st.session_state and st.session_state.new_articles:
        if st.button("Process and Save Articles"):
            with st.spinner("Processing articles with AI..."):
                knowledge_base = []
                
                # Process each new article
                for row in st.session_state.new_articles:
                    processed = process_article(row)
                    if processed:
                        knowledge_base.append(processed)
                
                st.session_state.knowledge_base = knowledge_base
                
                # Show success message
                if knowledge_base:
                    st.success(f"Successfully processed {len(knowledge_base)} articles.")
                else:
                    st.error("Failed to process any articles.")

    # FIXED: Separate section for processed articles - based on session state, not nested buttons
    if "knowledge_base" in st.session_state and st.session_state.knowledge_base:
        st.markdown("### Processed Articles")
        knowledge_df = pd.DataFrame(st.session_state.knowledge_base)
        st.dataframe(knowledge_df)
        
        # FIXED: This button is now independent and will work properly
        if st.button("Save to Database"):
            persist_knowledge_base_dynamodb(st.session_state.knowledge_base)

    # # Debug section
    # if "knowledge_base" in st.session_state and st.session_state.knowledge_base:
    #     st.markdown("### Debug Processed Articles")
        
    #     col_debug1, col_debug2 = st.columns(2)
        
    #     with col_debug1:
    #         if st.button("🔍 Debug Article Structure"):
    #             debug_article_save(st.session_state.knowledge_base)
        
    #     with col_debug2:
    #         if st.button("🧪 Test Article Save"):
    #             test_save_processed_articles()


def content_creation_section():
    st.markdown("# Content Creation")
    col1, col2 = st.columns([1, 2])
    
    with col1:
        # Retrieve articles from DynamoDB with pagination
        articles = get_all_articles()
        
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
            now = pd.Timestamp.utcnow()
            if date_filter_option == "Last 24 hrs":
                cutoff = now - pd.Timedelta(days=1)
            elif date_filter_option == "Last 3 days":
                cutoff = now - pd.Timedelta(days=3)
            elif date_filter_option == "Last week":
                cutoff = now - pd.Timedelta(days=7)
            elif date_filter_option == "Last month":
                cutoff = now - pd.Timedelta(days=30)
            
            # Make sure cutoff is timezone-aware to match the parsed timestamps
            if not cutoff.tzinfo:
                cutoff = cutoff.tz_localize('UTC')
            
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
                            model="o4-mini",
                            messages=st.session_state.conversation_thread,
                            max_completion_tokens=10000
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
                                    model="o4-mini",
                                    messages=st.session_state.conversation_thread,
                                    max_completion_tokens=10000
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
                                    model="o4-mini",
                                    messages=review_prompt,
                                    max_completion_tokens=10000
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
