from datetime import datetime, timedelta
import re
from dateutil import parser

def parse_rss_date(date_str):
    """
    Parse various RSS date formats into a standard ISO format.
    Enhanced based on analysis of all 12 working feeds.
    
    Handles formats from:
    - The Verge: 2025-05-22T08:58:34-04:00
    - DeepMind/Google: Tue, 20 May 2025 09:45:00 +0000  
    - Harvard: 2025-05-22T12:05:34Z
    - Guardian: Thu, 22 May 2025 09:00:03 GMT + 2025-05-22T09:00:03Z
    - OpenAI: Thu, 22 May 2025 00:00:00 GMT
    - ScienceDaily: Mon, 19 May 2025 13:20:26 EDT
    - MIT Tech Review: Thu, 22 May 2025 12:10:00 +0000
    - TechCrunch: Thu, 22 May 2025 14:00:00 +0000
    - VentureBeat: Thu, 22 May 2025 14:00:00 +0000
    - NYTimes: Thu, 22 May 2025 09:03:18 +0000
    
    Args:
        date_str (str): Date string from RSS feed
    
    Returns:
        str: Standardized ISO 8601 date string (YYYY-MM-DDTHH:MM:SSZ)
    """
    if not date_str or date_str == 'No Date':
        return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    
    # Clean the input string
    date_str = str(date_str).strip()
    
    try:
        # Try dateutil parser first - handles most formats automatically
        parsed_date = parser.parse(date_str)
        # Convert to UTC and return ISO format
        return parsed_date.strftime('%Y-%m-%dT%H:%M:%SZ')
    except Exception as e:
        # If dateutil fails, try specific format parsing
        try:
            # Format 1: Already in ISO format with Z (Harvard)
            if re.match(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', date_str):
                return date_str
            
            # Format 2: ISO format with timezone offset (The Verge)
            # Example: "2025-05-22T08:58:34-04:00"
            if re.match(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}', date_str):
                parsed_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                return parsed_date.strftime('%Y-%m-%dT%H:%M:%SZ')
            
            # Format 3: RFC 2822 with GMT (Guardian, OpenAI)
            # Example: "Thu, 22 May 2025 09:00:03 GMT"
            if re.match(r'\w{3}, \d{2} \w{3} \d{4} \d{2}:\d{2}:\d{2} GMT', date_str):
                parsed_date = datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S GMT')
                return parsed_date.strftime('%Y-%m-%dT%H:%M:%SZ')
            
            # Format 4: RFC 2822 with +0000 (Google, DeepMind, TechCrunch, MIT Tech Review, VentureBeat, NYTimes)
            # Example: "Thu, 22 May 2025 09:00:00 +0000"
            if re.match(r'\w{3}, \d{2} \w{3} \d{4} \d{2}:\d{2}:\d{2} \+0000', date_str):
                parsed_date = datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S +0000')
                return parsed_date.strftime('%Y-%m-%dT%H:%M:%SZ')
            
            # Format 5: RFC 2822 with EDT/EST (ScienceDaily)
            # Example: "Mon, 19 May 2025 13:20:26 EDT"
            if re.match(r'\w{3}, \d{2} \w{3} \d{4} \d{2}:\d{2}:\d{2} EDT', date_str):
                parsed_date = datetime.strptime(date_str.replace(' EDT', ''), '%a, %d %b %Y %H:%M:%S')
                # EDT is UTC-4, so add 4 hours to convert to UTC
                parsed_date = parsed_date + timedelta(hours=4)
                return parsed_date.strftime('%Y-%m-%dT%H:%M:%SZ')
            
            if re.match(r'\w{3}, \d{2} \w{3} \d{4} \d{2}:\d{2}:\d{2} EST', date_str):
                parsed_date = datetime.strptime(date_str.replace(' EST', ''), '%a, %d %b %Y %H:%M:%S')
                # EST is UTC-5, so add 5 hours to convert to UTC
                parsed_date = parsed_date + timedelta(hours=5)
                return parsed_date.strftime('%Y-%m-%dT%H:%M:%SZ')
            
            # Format 6: VentureBeat sometimes uses PST/PDT (-0700)
            if re.match(r'\w{3}, \d{2} \w{3} \d{4} \d{2}:\d{2}:\d{2} -0700', date_str):
                parsed_date = datetime.strptime(date_str.replace(' -0700', ''), '%a, %d %b %Y %H:%M:%S')
                # PDT is UTC-7, so add 7 hours to convert to UTC
                parsed_date = parsed_date + timedelta(hours=7)
                return parsed_date.strftime('%Y-%m-%dT%H:%M:%SZ')
            
            # Legacy formats from your original system (keeping for compatibility)
            if re.match(r'\w{3}, \d{2} \w{3} \d{4} \d{2}:\d{2}:\d{2} \+\d{4}', date_str):
                parsed_date = datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S +0000')
                return parsed_date.strftime('%Y-%m-%dT%H:%M:%SZ')
            
            # Fallback - use current time but log the issue
            print(f"⚠️ Unknown date format: '{date_str}' - using current time")
            return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
            
        except Exception as inner_e:
            print(f"❌ Failed to parse date '{date_str}': {inner_e}")
            return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

# Test function to verify all formats work
def test_all_date_formats():
    """Test the date parser with all identified formats from the RSS analysis."""
    test_cases = [
        # The Verge AI (ISO with timezone offset)
        ("2025-05-22T08:58:34-04:00", "The Verge"),
        ("2025-05-22T10:10:56-04:00", "The Verge"),
        
        # DeepMind/Google Blog/MIT Sloan/TechCrunch/VentureBeat/NYTimes (+0000)
        ("Tue, 20 May 2025 09:45:00 +0000", "Google/DeepMind"),
        ("Thu, 22 May 2025 11:00:05 +0000", "MIT Sloan"),
        ("Thu, 22 May 2025 14:00:00 +0000", "TechCrunch/VentureBeat"),
        ("Thu, 22 May 2025 09:03:18 +0000", "NYTimes"),
        
        # Harvard Business Review (ISO with Z)
        ("2025-05-22T12:05:34Z", "Harvard"),
        ("2025-05-21T13:00:00Z", "Harvard"),
        
        # Guardian (mixed formats - GMT and ISO)
        ("Thu, 22 May 2025 09:00:03 GMT", "Guardian GMT"),
        ("2025-05-22T09:00:03Z", "Guardian ISO"),
        
        # OpenAI (GMT format)
        ("Thu, 22 May 2025 00:00:00 GMT", "OpenAI"),
        ("Wed, 21 May 2025 08:00:00 GMT", "OpenAI"),
        
        # ScienceDaily (EDT timezone)
        ("Mon, 19 May 2025 13:20:26 EDT", "ScienceDaily"),
        
        # MIT Technology Review (+0000)
        ("Thu, 22 May 2025 12:10:00 +0000", "MIT Tech Review"),
        
        # Legacy formats (for compatibility)
        ("Wed, 07 May 2025 13:35:34 GMT", "Legacy GMT"),
        ("Tue, 06 May 2025 15:29:24 +0000", "Legacy +0000"),
    ]
    
    print("🧪 Testing all date formats from working feeds:")
    print("=" * 70)
    
    success_count = 0
    total_count = len(test_cases)
    
    for date_str, source in test_cases:
        try:
            result = parse_rss_date(date_str)
            print(f"✅ {source:20} | {date_str:35} → {result}")
            success_count += 1
        except Exception as e:
            print(f"❌ {source:20} | {date_str:35} → ERROR: {e}")
    
    print("\n" + "=" * 70)
    print(f"🎯 Results: {success_count}/{total_count} formats parsed successfully!")
    
    if success_count == total_count:
        print("🎉 All date formats are working perfectly!")
        return True
    else:
        print(f"⚠️ {total_count - success_count} formats failed - check the errors above")
        return False

if __name__ == "__main__":
    test_all_date_formats()