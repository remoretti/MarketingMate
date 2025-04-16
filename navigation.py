import streamlit as st
from auth import get_current_user, is_authenticated

def render_navigation():
    """Render navigation menu based on user role."""
    if not is_authenticated():
        return  # No navigation if not logged in
    
    user = get_current_user()
    
    # Set up navigation
    if 'current_page' not in st.session_state:
        st.session_state.current_page = "main"
    
    with st.sidebar:
        st.markdown("### Navigation")
        
        # Main app navigation
        if st.button("📊 Dashboard", key="nav_dashboard", 
                    type="primary" if st.session_state.current_page == "main" else "secondary"):
            st.session_state.current_page = "main"
            st.rerun()
        
        # User management (admin only)
        if user.get('role') == 'admin':
            if st.button("👥 User Management", key="nav_users",
                        type="primary" if st.session_state.current_page == "users" else "secondary"):
                st.session_state.current_page = "users"
                st.rerun()
        
        st.markdown("---")

def get_current_page():
    """Get the current page from session state."""
    if 'current_page' not in st.session_state:
        return "main"
    return st.session_state.current_page