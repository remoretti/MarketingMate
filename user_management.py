import streamlit as st
import boto3
import os
from auth import get_user_table, create_user, get_current_user, is_authenticated
import pandas as pd
from datetime import datetime

def render_user_management():
    """Render the user management page for admins."""
    # Check if user is authenticated and is an admin
    if not is_authenticated():
        st.error("You must be logged in to view this page.")
        return
    
    current_user = get_current_user()
    if current_user['role'] != 'admin':
        st.error("You do not have permission to access this page.")
        return
    
    st.title("User Management")
    
    # Get user table
    table = get_user_table()
    if not table:
        st.error("Failed to connect to user database.")
        return
    
    # Create tabs for different user management functions
    tab1, tab2 = st.tabs(["User List", "Add New User"])
    
    with tab1:
        st.header("Current Users")
        
        # Get all users
        try:
            response = table.scan()
            users = response.get('Items', [])
            
            if not users:
                st.info("No users found in the database.")
            else:
                # Convert to DataFrame for display
                df_users = pd.DataFrame(users)
                
                # Format the DataFrame for display
                if 'password' in df_users.columns:
                    df_users = df_users.drop(columns=['password'])  # Don't show password hashes
                
                # Format timestamps
                if 'created_at' in df_users.columns:
                    df_users['created_at'] = pd.to_datetime(df_users['created_at']).dt.strftime('%Y-%m-%d %H:%M:%S')
                
                if 'last_login' in df_users.columns:
                    # Handle None values in last_login
                    df_users['last_login'] = df_users['last_login'].apply(
                        lambda x: pd.to_datetime(x).strftime('%Y-%m-%d %H:%M:%S') if x else "Never"
                    )
                
                # Display the DataFrame
                st.dataframe(df_users)
                
                # Delete user functionality
                st.subheader("Delete User")
                user_to_delete = st.selectbox("Select user to delete:", df_users['email'].tolist())
                
                if st.button("Delete Selected User"):
                    if user_to_delete == current_user['email']:
                        st.error("You cannot delete your own account.")
                    else:
                        try:
                            table.delete_item(Key={'email': user_to_delete})
                            st.success(f"User {user_to_delete} has been deleted.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error deleting user: {str(e)}")
        except Exception as e:
            st.error(f"Error retrieving users: {str(e)}")
    
    with tab2:
        st.header("Add New User")
        
        # Form for adding a new user
        with st.form("add_user_form"):
            new_email = st.text_input("Email Address")
            new_password = st.text_input("Password", type="password")
            confirm_password = st.text_input("Confirm Password", type="password")
            role = st.selectbox("Role", ["user", "admin"])
            
            submit = st.form_submit_button("Add User")
            
            if submit:
                if not new_email or not new_password:
                    st.error("Email and password are required.")
                elif new_password != confirm_password:
                    st.error("Passwords do not match.")
                else:
                    success, message = create_user(new_email, new_password, role)
                    if success:
                        st.success(message)
                    else:
                        st.error(message)

def app():
    """Main function to run the user management app."""
    render_user_management()

if __name__ == "__main__":
    app()