import boto3
import os
from dotenv import load_dotenv
from date_utils import parse_rss_date
import time

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

def update_timestamps():
    print("Starting timestamp standardization...")
    
    # Get all items with pagination
    items = []
    last_evaluated_key = None
    
    while True:
        if last_evaluated_key:
            response = table.scan(ExclusiveStartKey=last_evaluated_key)
        else:
            response = table.scan()
        
        items.extend(response.get('Items', []))
        
        last_evaluated_key = response.get('LastEvaluatedKey')
        if not last_evaluated_key:
            break
    
    updated_count = 0
    skipped_count = 0
    
    for item in items:
        if 'timestamp' in item:
            original_date = item['timestamp']
            
            # Skip if already in ISO format
            if original_date.count('-') == 2 and 'T' in original_date and 'Z' in original_date:
                skipped_count += 1
                continue
            
            # Parse and standardize the date
            standardized_date = parse_rss_date(original_date)
            
            if standardized_date != original_date:
                # Keep original date in a new field
                item['original_date'] = original_date
                item['timestamp'] = standardized_date
                
                # Update the item in DynamoDB
                try:
                    if 'url' in item:  # Make sure we have the key
                        table.put_item(Item=item)
                        updated_count += 1
                        print(f"Updated: '{original_date}' -> '{standardized_date}'")
                        
                        # Add a small delay to avoid hitting DynamoDB rate limits
                        time.sleep(0.1)
                except Exception as e:
                    print(f"Error updating item: {e}")
        
    print(f"Updated {updated_count} timestamps")
    print(f"Skipped {skipped_count} timestamps (already in ISO format)")

# Run the update
if __name__ == "__main__":
    print("This script will update all non-ISO format timestamps in your database.")
    print("Do you want to continue? (y/n)")
    
    if input().lower().strip() == 'y':
        update_timestamps()
    else:
        print("Operation cancelled.")