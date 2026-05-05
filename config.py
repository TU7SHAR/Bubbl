import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'defaulter-2002')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 30,"pool_timeout": 10}
    
    UPLOAD_FOLDER = os.path.join(basedir, 'uploads')
    SCRAPE_FOLDER = os.path.join(basedir, 'scraped_docs') 
  
  
    # HOST_URL = os.getenv('HOST_URL', 'https://chatbot-c53nl.ondigitalocean.app/')
    HOST_URL = os.getenv('HOST_URL', 'https://chatbot-c53nl.ondigitalocean.app/')
  
    COMPANY_NAME_FIRST = os.getenv('COMPANY_NAME_FRONT')
    COMPANY_LAST_NAME = os.getenv('COMPANY_NAME_BACK')
    SUPPORT_EMAIL = os.getenv('SUPPORT_EMAIL')
    OFFICE_LOCATION = os.getenv('OFFICE_LOCATION')
  
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  
    ALLOWED_EXTENSIONS = {'txt', 'doc', 'docx', 'xls', 'xlsx', 'md', 'html', 'pdf'}
    
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    FIRECRAWL_API_KEY = os.getenv('FIRECRAWL_API_KEY')