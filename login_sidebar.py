import streamlit as st
from auth import authenticate_user, logout_user, is_authenticated, get_current_user

def render_login_sidebar():
    """Render the login sidebar component."""
    with st.sidebar:
        st.title("MarketingMate")
        
        if is_authenticated():
            user = get_current_user()
            st.success(f"Logged in as: {user['email']}")
            
            if st.button("Logout"):
                logout_user()
                st.rerun()
        else:
            st.subheader("Login")
            
            with st.form("login_form"):
                email = st.text_input("Email")
                password = st.text_input("Password", type="password")
                submit_button = st.form_submit_button("Login")
                
                if submit_button:
                    if not email or not password:
                        st.error("Please enter both email and password")
                    else:
                        success, message = authenticate_user(email, password)
                        if success:
                            st.success(message)
                            st.rerun()
                        else:
                            st.error(message)
            
            st.info("Contact your administrator if you need access.")

def check_authentication():
    """Check authentication and show appropriate view."""
    if not is_authenticated():
        # If not logged in, show only the login sidebar
        render_login_sidebar()
        st.warning("Please login to access MarketingMate.")
        return False
    else:
        # If logged in, show the login sidebar AND return True to show the main app
        render_login_sidebar()
        return True