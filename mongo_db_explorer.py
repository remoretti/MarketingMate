from pymongo import MongoClient
import os
from dotenv import load_dotenv

# Load environment variables and initialize client
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["MarketingMate"]
articles_collection = db["articles"]

# Retrieve and print all articles
for article in articles_collection.find():
    print(article)
