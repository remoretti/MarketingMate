import boto3
import os
import streamlit as st
import hashlib
import secrets
import hmac
from datetime import datetime, timedelta
import traceback

def get_user_table():
    """Initialize and return the DynamoDB users table."""
    try:
        dynamodb = boto3.resource(
            'dynamodb', 
            region_name=os.getenv('AWS_DEFAULT_REGION', 'us-east-1'),
            aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
        )
        
        table = dynamodb.Table('MarketingMateUsers')
        return table
    except Exception as e:
        st.error(f"DynamoDB Users Table Access Error: {e}")
        st.error(f"Full Error Details: {traceback.format_exc()}")
        return None

def hash_password(password, salt=None):
    """Hash a password for storing."""
    if salt is None:
        salt = secrets.token_hex(16)
    
    # Use HMAC with SHA-256 for password hashing
    key = hashlib.pbkdf2_hmac(
        'sha256', 
        password.encode('utf-8'), 
        salt.encode('utf-8'), 
        100000,  # 100,000 iterations
        dklen=128
    )
    
    return salt + ":" + key.hex()

def verify_password(stored_password, provided_password):
    """Verify a stored password against a provided password."""
    salt, key = stored_password.split(":")
    return stored_password == hash_password(provided_password, salt)

def create_user(email, password, role="user"):
    """Create a new user in the database."""
    table = get_user_table()
    if not table:
        return False, "Database connection error"
    
    # Check if user already exists
    try:
        response = table.get_item(Key={'email': email})
        if 'Item' in response:
            return False, "User already exists"
        
        # Hash the password before storing
        hashed_pw = hash_password(password)
        
        # Store the new user
        table.put_item(Item={
            'email': email,
            'password': hashed_pw,
            'role': role,
            'created_at': datetime.utcnow().isoformat(),
            'last_login': None
        })
        
        return True, "User created successfully"
    except Exception as e:
        return False, f"Error creating user: {str(e)}"

def authenticate_user(email, password):
    """Authenticate a user by email and password."""
    table = get_user_table()
    if not table:
        return False, "Database connection error"
    
    try:
        response = table.get_item(Key={'email': email})
        if 'Item' not in response:
            return False, "Invalid email or password"
        
        user = response['Item']
        if verify_password(user['password'], password):
            # Update last login time
            table.update_item(
                Key={'email': email},
                UpdateExpression="set last_login=:l",
                ExpressionAttributeValues={':l': datetime.utcnow().isoformat()}
            )
            
            # Set user in session state
            st.session_state.user = {
                'email': email,
                'role': user['role'],
                'logged_in': True
            }
            
            return True, "Login successful"
        else:
            return False, "Invalid email or password"
    except Exception as e:
        return False, f"Login error: {str(e)}"

def is_authenticated():
    """Check if a user is authenticated in the current session."""
    return 'user' in st.session_state and st.session_state.user.get('logged_in', False)

def get_current_user():
    """Return the current authenticated user."""
    if is_authenticated():
        return st.session_state.user
    return None

def logout_user():
    """Log out the current user."""
    if 'user' in st.session_state:
        del st.session_state.user
    return True

def init_auth():
    """Initialize authentication - create admin user if doesn't exist."""
    table = get_user_table()
    if not table:
        st.error("Failed to initialize authentication system")
        return
    
    # Check if admin user exists, create if it doesn't
    admin_email = os.getenv('ADMIN_EMAIL')
    admin_password = os.getenv('ADMIN_PASSWORD')
    
    # Verify that environment variables are set
    if not admin_email or not admin_password:
        st.error("Admin credentials not found in environment variables. Please set ADMIN_EMAIL and ADMIN_PASSWORD.")
        return
    
    try:
        response = table.get_item(Key={'email': admin_email})
        if 'Item' not in response:
            create_user(admin_email, admin_password, role="admin")
            st.success(f"Admin user {admin_email} created successfully.")
    except Exception as e:
        st.error(f"Error initializing authentication: {str(e)}")