import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

class Config:
    SECRET_KEY = os.environ['SECRET_KEY']  # No fallback — crash on startup if missing
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,       # Recycle connections every 5 min
        "pool_timeout": 20,        # Wait up to 20s for a connection
        "pool_size": 5,            # 5 per process (gunicorn×2 + celery×1 = 15 total, under NeonDB free 20 limit)
        "max_overflow": 3,         # Allow 3 extra during spikes (max 8 per process, 24 total — brief bursts OK)
    }
    
    UPLOAD_FOLDER = os.path.join(basedir, 'uploads')
    SCRAPE_FOLDER = os.path.join(basedir, 'scraped_docs') 
  
  
    # HOST_URL = os.getenv('HOST_URL', 'http://168.144.123.62:8080/')
    HOST_URL = os.getenv('HOST_URL')
  
    COMPANY_NAME_FIRST = os.getenv('COMPANY_NAME_FRONT')
    COMPANY_LAST_NAME = os.getenv('COMPANY_NAME_BACK')
    SUPPORT_EMAIL = os.getenv('SUPPORT_EMAIL')
    OFFICE_LOCATION = os.getenv('OFFICE_LOCATION')
  
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  
    ALLOWED_EXTENSIONS = {'txt', 'doc', 'docx', 'xls', 'xlsx', 'md', 'html', 'pdf'}
    
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    FIRECRAWL_API_KEY = os.getenv('FIRECRAWL_API_KEY')

    # --- PADDLE (Payment Gateway) ---
    PADDLE_API_KEY = os.getenv('PADDLE_API_KEY')
    PADDLE_WEBHOOK_SECRET = os.getenv('PADDLE_WEBHOOK_SECRET')
    PADDLE_ENVIRONMENT = os.getenv('PADDLE_ENVIRONMENT', 'sandbox')  # 'sandbox' or 'production'
    PADDLE_CLIENT_TOKEN = os.getenv('PADDLE_CLIENT_TOKEN')  # For frontend Paddle.js
    
    # --- ANALYTICS ---
    GA4_MEASUREMENT_ID = os.getenv('GA4_MEASUREMENT_ID')       # e.g. G-XXXXXXXXXX
    META_PIXEL_ID = os.getenv('META_PIXEL_ID')                 # e.g. 1234567890
    CLARITY_ID = os.getenv('CLARITY_ID')                       # e.g. abcdef123