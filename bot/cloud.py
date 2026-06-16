import os
import time
from dotenv import load_dotenv
from google import genai

load_dotenv()

def get_gemini_client():
    return genai.Client(api_key=os.getenv('GEMINI_API_KEY'))

def create_dynamic_store(bot_name):
    """Creates a new vector store on Google Cloud and returns its ID."""
    try:
        client = get_gemini_client()
        store_config = {'display_name': bot_name}
        
        vector_store = client.file_search_stores.create(config=store_config)
        store_id = vector_store.name 
        
        print(f"Successfully created new Vector Store: {store_id}")
        return store_id
        
    except Exception as error: 
        print(f"Error creating dynamic store: {error}") 
        return None

def upload_to_gemini(file_path, target_store_id):
    """Uploads and indexes a file directly into a Gemini vector store"""
    try:
        client = get_gemini_client()
        print(f"Initiating Gemini upload for: {file_path}")
        
        operation = client.file_search_stores.upload_to_file_search_store(
            file=file_path,
            file_search_store_name=target_store_id
        )
        
        print("Waiting for Google servers to process and index document...")
        while not operation.done:
            time.sleep(5)
            operation = client.operations.get(operation)
            print("...still indexing...")
            
        print(f" Document ACTIVE and searchable: {file_path}")

    except Exception as e: 
        print(f" Gemini Upload Error: {e}")
        raise e    
  
def delete_from_gemini(l_filename):
    """Finds file from general storage and deletes it safely"""
    try:
        client = get_gemini_client()
        print(f"Searching for filename to delete: {l_filename}")
        
        for g_file in client.files.list():
            if g_file.display_name == l_filename:
                # Pass the object directly to avoid the keyword bug here too
                client.files.delete(g_file)
                print(f"Deleted global file: {l_filename}")

    except Exception as e:
        print(f"Error deleting file: {e}")