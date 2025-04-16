import streamlit as st
from dotenv import load_dotenv
import os
import boto3

# Set page config
st.set_page_config(
    page_title="MarketingMate",
    page_icon="📰",
    layout="wide"
)

# Import custom modules
from auth import init_auth
from login_sidebar import render_login_sidebar, check_authentication
from navigation import render_navigation, get_current_page
import app_dynamodb
import user_management

# Load environment variables
load_dotenv()

# Initialize authentication
init_auth()



def main():
    """Main function to run the MarketingMate app."""
    # Render login sidebar
    is_authenticated = check_authentication()
    
    if is_authenticated:
        # Render navigation if authenticated
        render_navigation()
        
        # Get current page
        current_page = get_current_page()
        
        # Display the appropriate page
        if current_page == "main":
            app_dynamodb.app()
        elif current_page == "users":
            user_management.app()
    else:
        # Display login message
        st.title("Welcome to MarketingMate")
        st.write("Please login using the sidebar to access the application.")
        
        # Add some informative content for non-authenticated users
        st.markdown("""
        ## MarketingMate Features
        
        * **RSS Feed Monitoring** - Stay updated with the latest articles from various sources
        * **Content Analysis** - AI-powered analysis of article relevance to key topics
        * **Content Creation** - Generate customized content for different platforms
        
        For access, please contact your administrator.
        """)

if __name__ == "__main__":
    main()