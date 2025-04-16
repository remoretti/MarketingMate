# Use an official Python image as a base
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create and set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file first, so dependencies can be cached
COPY requirements.txt /app/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install AWS CLI
RUN pip install awscli

# Copy the rest of your application code
COPY . /app/

# Expose the port your app runs on (Streamlit default is 8501)
EXPOSE 8501

# Run the app
#CMD ["streamlit", "run", "app_dynamodb.py", "--server.enableCORS", "false"]
CMD ["streamlit", "run", "app.py", "--server.enableCORS", "false"]