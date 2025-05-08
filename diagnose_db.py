import boto3
import os
from dotenv import load_dotenv
import pandas as pd
from datetime import datetime

# Load environment variables
load_dotenv()

# Initialize DynamoDB client
dynamodb = boto3.resource(
    'dynamodb', 
    region_name=os.getenv('AWS_DEFAULT_REGION', 'us-east-1'),
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
)

# Get the table
table = dynamodb.Table('MarketingMateDB')

def diagnose_database():
    print("Starting database diagnosis...")
    
    # Get exact count with pagination
    items = []
    last_evaluated_key = None
    
    # Scan the entire table with pagination
    print("Scanning table with pagination...")
    while True:
        if last_evaluated_key:
            response = table.scan(ExclusiveStartKey=last_evaluated_key)
        else:
            response = table.scan()
        
        items.extend(response.get('Items', []))
        print(f"Retrieved {len(response.get('Items', []))} items...")
        
        last_evaluated_key = response.get('LastEvaluatedKey')
        if not last_evaluated_key:
            break
    
    total_items = len(items)
    print(f"\nTotal items retrieved: {total_items}")
    
    # Check for duplicate titles and URLs
    print("\nChecking for duplicates...")
    titles = {}
    urls = {}
    
    for item in items:
        title = item.get('Title', '')
        url = item.get('url', '')
        
        if title in titles:
            titles[title] += 1
        else:
            titles[title] = 1
            
        if url in urls:
            urls[url] += 1
        else:
            urls[url] = 1
    
    duplicate_titles = {t: c for t, c in titles.items() if c > 1 and t}
    duplicate_urls = {u: c for u, c in urls.items() if c > 1 and u}
    
    print(f"Found {len(duplicate_titles)} titles with duplicates")
    print(f"Found {len(duplicate_urls)} URLs with duplicates")
    
    # Check for missing fields
    print("\nChecking for items with missing fields...")
    missing_title = len([item for item in items if 'Title' not in item])
    missing_url = len([item for item in items if 'url' not in item])
    missing_timestamp = len([item for item in items if 'timestamp' not in item])
    missing_text = len([item for item in items if 'text' not in item])
    
    print(f"Items missing Title: {missing_title}")
    print(f"Items missing URL: {missing_url}")
    print(f"Items missing timestamp: {missing_timestamp}")
    print(f"Items missing text: {missing_text}")
    
    # Check timestamp formats
    print("\nAnalyzing timestamp formats...")
    iso_format_count = 0
    non_iso_format_count = 0
    
    for item in items:
        timestamp = item.get('timestamp', '')
        if timestamp and isinstance(timestamp, str):
            # Check if timestamp matches ISO format (YYYY-MM-DDTHH:MM:SSZ)
            if timestamp.count('-') == 2 and 'T' in timestamp and 'Z' in timestamp:
                iso_format_count += 1
            else:
                non_iso_format_count += 1
    
    print(f"Items with ISO format timestamps: {iso_format_count}")
    print(f"Items with non-ISO format timestamps: {non_iso_format_count}")
    
    # Display sample duplicates if they exist
    if duplicate_urls:
        print("\nSample of duplicate URLs:")
        count = 0
        for url, num in duplicate_urls.items():
            if count >= 3:  # Limit to 3 examples
                break
                
            print(f"\nDuplicates for URL: {url}")
            duplicates = [item for item in items if item.get('url') == url]
            
            for i, dup in enumerate(duplicates):
                print(f"  Duplicate {i+1}:")
                print(f"    Title: {dup.get('Title', 'Missing')}")
                print(f"    Timestamp: {dup.get('timestamp', 'Missing')}")
                print(f"    Has original_date: {'Yes' if 'original_date' in dup else 'No'}")
            
            count += 1
    
    # Return all the items for potential further analysis
    return items

# Run the diagnosis
all_items = diagnose_database()

# Optional: Save results to CSV for further analysis
print("\nWould you like to save the database items to a CSV file for analysis? (y/n)")
save_to_csv = input().lower().strip() == 'y'

if save_to_csv:
    print("Converting to DataFrame...")
    # Normalize the data for DataFrame
    normalized_items = []
    for item in all_items:
        normalized_item = {
            'Title': item.get('Title', ''),
            'url': item.get('url', ''),
            'timestamp': item.get('timestamp', ''),
            'original_date': item.get('original_date', ''),
            'source': item.get('source', ''),
            'has_text': 'text' in item
        }
        normalized_items.append(normalized_item)
    
    df = pd.DataFrame(normalized_items)
    filename = f"dynamodb_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    df.to_csv(filename, index=False)
    print(f"Data exported to {filename}")