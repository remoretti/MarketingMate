from datetime import datetime
import re
from dateutil import parser

def parse_rss_date(date_str):
    """
    Parse various RSS date formats into a standard ISO format.
    
    Args:
        date_str (str): Date string from RSS feed
    
    Returns:
        str: Standardized ISO 8601 date string (YYYY-MM-DDTHH:MM:SSZ)
    """
    if not date_str or date_str == 'No Date':
        # Return current time if no date is provided
        return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    
    try:
        # Try parsing with dateutil - handles most formats
        parsed_date = parser.parse(date_str)
        return parsed_date.strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception as e:
        # If parsing fails, try custom parsing for common formats
        try:
            # For formats like "Wed, 07 May 2025 13:35:34 GMT"
            if re.match(r'\w{3}, \d{2} \w{3} \d{4} \d{2}:\d{2}:\d{2} GMT', date_str):
                parsed_date = datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S GMT')
                return parsed_date.strftime('%Y-%m-%dT%H:%M:%SZ')
            
            # For formats like "Tue, 06 May 2025 15:29:24 +0000"
            if re.match(r'\w{3}, \d{2} \w{3} \d{4} \d{2}:\d{2}:\d{2} \+\d{4}', date_str):
                parsed_date = datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S +0000')
                return parsed_date.strftime('%Y-%m-%dT%H:%M:%SZ')
            
            # For ISO format "2025-05-07T14:34:13Z"
            if re.match(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', date_str):
                return date_str  # Already in our target format
                
            # Last fallback - try simple parsing with a flexible approach
            return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        except Exception as inner_e:
            print(f"Failed to parse date '{date_str}': {inner_e}")
            return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')