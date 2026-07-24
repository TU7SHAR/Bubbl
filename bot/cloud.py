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
  
def delete_from_gemini(l_filename, store_id=None):
    """
    Deletes a file from Gemini — both from the File Search Store (vector store)
    AND from the general Files API storage.
    
    If store_id is provided, searches the store's documents list and deletes the
    matching document (removes it from the vector index). Then also deletes from
    the general Files API as a cleanup.
    
    Without store_id, only deletes from Files API (legacy behavior — won't remove
    from vector store).
    """
    try:
        client = get_gemini_client()
        print(f"[delete] Searching for: {l_filename}")

        # 1. Delete from File Search Store (vector store) — the important one
        if store_id:
            try:
                # List all documents in the store and find the matching one
                for doc in client.file_search_stores.documents.list(parent=store_id):
                    # Match by display_name (what we set on upload)
                    doc_display = getattr(doc, 'display_name', '') or ''
                    doc_name = getattr(doc, 'name', '') or ''
                    
                    if doc_display == l_filename or l_filename in doc_display:
                        client.file_search_stores.documents.delete(
                            name=doc_name,
                            config={'force': True}
                        )
                        print(f"[delete] Removed from vector store: {doc_name}")
                        break
                else:
                    print(f"[delete] Not found in store {store_id} by display_name: {l_filename}")
            except Exception as e:
                print(f"[delete] Error removing from vector store: {e}")

        # 2. Delete from general Files API (cleanup — files expire after 48h anyway)
        try:
            for g_file in client.files.list():
                if g_file.display_name == l_filename:
                    client.files.delete(g_file)
                    print(f"[delete] Removed from Files API: {l_filename}")
                    break
        except Exception as e:
            print(f"[delete] Error removing from Files API (non-critical): {e}")

    except Exception as e:
        print(f"[delete] Error: {e}")