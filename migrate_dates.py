import boto3
from boto3.dynamodb.conditions import Key
import os
from dotenv import load_dotenv
import time
from date_utils import parse_rss_date
import re

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

def migrate_dates():
    print("Starting date migration...")
    
    # Get all records from the table
    response = table.scan()
    items = response.get('Items', [])
    
    total_items = len(items)
    print(f"Found {total_items} records to process")
    
    # Process each item
    updated_count = 0
    skipped_count = 0
    error_count = 0
    
    for i, item in enumerate(items):
        try:
            # Print progress
            if i % 10 == 0:
                print(f"Processing item {i+1} of {total_items}...")
            
            # Check if timestamp exists
            if 'timestamp' in item:
                original_date = item['timestamp']
                
                # Check if the date is already in ISO format
                if re.match(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', original_date):
                    skipped_count += 1
                    continue
                
                # Parse and standardize the date
                standardized_date = parse_rss_date(original_date)
                
                # Only update if the date format changed
                if standardized_date != original_date:
                    # Keep original date in a new field for reference
                    item['original_date'] = original_date
                    item['timestamp'] = standardized_date
                    
                    # Update the item in DynamoDB
                    table.put_item(Item=item)
                    updated_count += 1
                    
                    # Print sample updates
                    if updated_count <= 5:
                        print(f"Updated: '{original_date}' -> '{standardized_date}'")
                    
                    # Add a small delay to avoid hitting DynamoDB rate limits
                    time.sleep(0.1)
                else:
                    skipped_count += 1
            else:
                skipped_count += 1
                
        except Exception as e:
            print(f"Error updating item: {e}")
            error_count += 1
    
    print("\nMigration complete!")
    print(f"Total items: {total_items}")
    print(f"Updated: {updated_count}")
    print(f"Skipped: {skipped_count}")
    print(f"Errors: {error_count}")

# Run the migration
if __name__ == "__main__":
    # Ask for confirmation before proceeding
    confirmation = input("This will update date formats in your database. Continue? (y/n): ")
    if confirmation.lower() == 'y':
        migrate_dates()
    else:
        print("Migration cancelled.")