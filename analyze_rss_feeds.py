import requests
import feedparser
import pandas as pd
from datetime import datetime
import json
import traceback

def analyze_single_feed(url, source_name):
    """Analyze a single RSS feed and return structure information."""
    print(f"\n{'='*60}")
    print(f"ANALYZING: {source_name}")
    print(f"URL: {url}")
    print(f"{'='*60}")
    
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; MyRSSReader/1.0)'}
    
    try:
        # Fetch the feed
        print("Fetching feed...")
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # Parse with feedparser
        feed = feedparser.parse(response.content)
        
        # Basic feed info
        feed_info = {
            'source_name': source_name,
            'url': url,
            'status': 'SUCCESS',
            'feed_title': getattr(feed.feed, 'title', 'Unknown'),
            'feed_description': getattr(feed.feed, 'description', 'Unknown'),
            'total_entries': len(feed.entries),
            'feed_language': getattr(feed.feed, 'language', 'Unknown'),
            'last_updated': getattr(feed.feed, 'updated', 'Unknown'),
        }
        
        print(f"✅ Feed fetched successfully!")
        print(f"   Title: {feed_info['feed_title']}")
        print(f"   Entries found: {feed_info['total_entries']}")
        print(f"   Last updated: {feed_info['last_updated']}")
        
        # Analyze entries (first 3 for detailed analysis)
        entries_analysis = []
        sample_entries = feed.entries[:3] if len(feed.entries) >= 3 else feed.entries
        
        print(f"\n📊 ANALYZING FIRST {len(sample_entries)} ENTRIES:")
        
        for i, entry in enumerate(sample_entries, 1):
            print(f"\n--- Entry {i} ---")
            
            # Extract all available fields
            entry_data = {
                'entry_number': i,
                'title': getattr(entry, 'title', 'NO TITLE'),
                'link': getattr(entry, 'link', 'NO LINK'),
                'summary': getattr(entry, 'summary', getattr(entry, 'description', 'NO SUMMARY')),
                'published': getattr(entry, 'published', 'NO PUBLISHED'),
                'updated': getattr(entry, 'updated', 'NO UPDATED'),
                'author': getattr(entry, 'author', 'NO AUTHOR'),
                'id': getattr(entry, 'id', 'NO ID'),
            }
            
            # Get all available date fields
            date_fields = {}
            for field in ['published', 'updated', 'created', 'modified']:
                if hasattr(entry, field):
                    date_fields[field] = getattr(entry, field)
            
            entry_data['all_date_fields'] = date_fields
            
            # Show key info
            print(f"   Title: {entry_data['title'][:80]}...")
            print(f"   Link: {entry_data['link']}")
            print(f"   Published: {entry_data['published']}")
            print(f"   Updated: {entry_data['updated']}")
            print(f"   Summary length: {len(entry_data['summary'])} chars")
            print(f"   All date fields: {list(date_fields.keys())}")
            
            entries_analysis.append(entry_data)
        
        # Date format analysis
        print(f"\n📅 DATE FORMAT ANALYSIS:")
        unique_date_formats = set()
        for entry in sample_entries:
            for field in ['published', 'updated']:
                if hasattr(entry, field):
                    date_val = getattr(entry, field)
                    if date_val:
                        unique_date_formats.add(f"{field}: {date_val}")
        
        for date_format in unique_date_formats:
            print(f"   {date_format}")
        
        # Field availability analysis
        print(f"\n📋 FIELD AVAILABILITY:")
        field_availability = {}
        all_fields = set()
        
        for entry in sample_entries:
            for key in dir(entry):
                if not key.startswith('_'):
                    all_fields.add(key)
        
        for field in sorted(all_fields):
            count = sum(1 for entry in sample_entries if hasattr(entry, field) and getattr(entry, field))
            field_availability[field] = f"{count}/{len(sample_entries)}"
            print(f"   {field}: {count}/{len(sample_entries)} entries")
        
        feed_info.update({
            'sample_entries': entries_analysis,
            'unique_date_formats': list(unique_date_formats),
            'field_availability': field_availability,
            'error': None
        })
        
        return feed_info
        
    except requests.RequestException as e:
        error_msg = f"Request error: {str(e)}"
        print(f"❌ {error_msg}")
        return {
            'source_name': source_name,
            'url': url,
            'status': 'REQUEST_ERROR',
            'error': error_msg,
            'total_entries': 0
        }
    
    except Exception as e:
        error_msg = f"Parsing error: {str(e)}"
        print(f"❌ {error_msg}")
        print(f"Traceback: {traceback.format_exc()}")
        return {
            'source_name': source_name,
            'url': url,
            'status': 'PARSING_ERROR',
            'error': error_msg,
            'total_entries': 0
        }

def main():
    """Main function to analyze all RSS feeds."""
    
    # Your new RSS feed list
    feed_sources = {
        "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml": "THE VERGE AI",
        "https://deepmind.com/blog/feed/basic/": "DEEP MIND",
        "https://www.blog.google/technology/ai/rss/": "GOOGLE BLOG AI",
        "http://feeds.harvardbusiness.org/harvardbusiness/": "HARVARD BUSINESS REVIEW",
        "http://feeds.feedburner.com/mitsmr": "MIT Sloan Management Review",
        "https://www.technologyreview.com/feed/": "MIT Technology Review Main Feed",
        #"https://www.technologyreview.com/topnews.rss": "MIT Technology Review Top News",
        "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml": "New York Times - Technology",
        "https://openai.com/news/rss.xml": "OPEN AI news",
        #"https://openai.com/blog/rss.xml": "OPEN AI blog",
        "http://www.sciencedaily.com/rss/computers_math/artificial_intelligence.xml": "ScienceDaily - Artificial Intelligence",
        "https://techcrunch.com/feed/": "TechCrunch",
        "http://www.guardian.co.uk/technology/artificialintelligenceai/rss": "The Guardian - Artificial intelligence",
        "http://venturebeat.com/feed/": "VentureBeat"
    }
    
    print("🔍 RSS FEED ANALYSIS TOOL")
    print("=" * 80)
    print(f"Analyzing {len(feed_sources)} RSS feeds...")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    all_results = []
    successful_feeds = 0
    failed_feeds = 0
    
    for url, source_name in feed_sources.items():
        result = analyze_single_feed(url, source_name)
        all_results.append(result)
        
        if result['status'] == 'SUCCESS':
            successful_feeds += 1
        else:
            failed_feeds += 1
    
    # Summary report
    print(f"\n{'='*80}")
    print("📊 ANALYSIS SUMMARY")
    print(f"{'='*80}")
    print(f"Total feeds analyzed: {len(feed_sources)}")
    print(f"Successful: {successful_feeds}")
    print(f"Failed: {failed_feeds}")
    
    print(f"\n✅ SUCCESSFUL FEEDS:")
    for result in all_results:
        if result['status'] == 'SUCCESS':
            print(f"   • {result['source_name']}: {result['total_entries']} entries")
    
    print(f"\n❌ FAILED FEEDS:")
    for result in all_results:
        if result['status'] != 'SUCCESS':
            print(f"   • {result['source_name']}: {result['error']}")
    
    # Save detailed results to JSON file
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"rss_feed_analysis_{timestamp}.json"
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"\n💾 Detailed analysis saved to: {filename}")
    
    # Create a summary CSV
    summary_data = []
    for result in all_results:
        summary_data.append({
            'Source Name': result['source_name'],
            'URL': result['url'],
            'Status': result['status'],
            'Total Entries': result.get('total_entries', 0),
            'Feed Title': result.get('feed_title', 'N/A'),
            'Error': result.get('error', 'N/A')
        })
    
    df = pd.DataFrame(summary_data)
    csv_filename = f"rss_feed_summary_{timestamp}.csv"
    df.to_csv(csv_filename, index=False)
    print(f"📈 Summary CSV saved to: {csv_filename}")
    
    return all_results

if __name__ == "__main__":
    # Install required packages if needed
    try:
        import feedparser
        import pandas as pd
    except ImportError as e:
        print(f"Missing required package: {e}")
        print("Please install with: pip install feedparser pandas")
        exit(1)
    
    results = main()