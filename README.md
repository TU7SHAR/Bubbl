# 💬 Bubbl: Custom AI Agent SaaS Platform

Bubbl is a comprehensive platform enabling businesses to create, customize, and deploy AI chatbots trained exclusively on their own organizational data (PDFs, URLs, and Text). Built with a focus on speed, security, and data integrity, Bubbl provides a seamless transition from raw company data to an embedded, intelligent support agent.

## 🚀 Key Features

* **Multi-Source Knowledge Ingestion:** Train bots via direct file uploads (PDF, DOCX, TXT), raw text snippets, custom Q&A pairs, and automated website scraping.
* **"Two-Step" Vector Synchronization:** Engineered a custom backend bypass to handle Google SDK latency bugs. The system actively polls Google servers and strictly locks threads until a document is verified as `ACTIVE` before attaching it to the bot, preventing AI hallucination.
* **Bot Customization Engine:** Complete UI control over the chatbot widget, including Brand Colors, Avatars, Light/Dark Modes, and customizable Glassmorphism (blur/opacity parameters).
* **Security & Access Control:** Bots can be set to 'Public' or 'Private' (requiring 4-character decryption keys). Implemented CSP (Content-Security-Policy) to lock widget embedding to allowed domains only.
* **Admin Dashboard & Context Switching:** Centralized hub for managing multiple custom bots, viewing ingested files, and seamlessly switching active contex.
* **Advanced Contact & Support System:** Built a professional contact pipeline utilizing the `email-validator` library (performing real-time MX-record DNS checks to prevent fake emails) and secure SMTP for instant team alerts and automated user replies.

## 🛠️ Tech Stack

* **Frontend:** HTML5, Custom CSS (Glassmorphism UI), Vanilla JavaScript (ensuring ultra-fast widget load times without heavy frameworks).
* **Backend:** Python, Flask, SQLAlchemy (ORM).
* **AI Engine & Vector DB:** Google GenAI SDK (Gemini 3.1 Flash Lite) + Google Cloud File Search Stores.
* **Web Crawling Engine:** Firecrawl API + Beautiful Soup.
* **Database:** PostgreSQL (Hosted on Neon Serverless).

## 🗄️ Database Schema

The system operates on a highly relational PostgreSQL database mapped via SQLAlchemy:
1. **Users:** Manages credentials, organizational IDs, role assignments (admin/member), and OTP verification.
2. **Bots:** Stores core chatbot configurations, system prompts (Sales, Support, General), visibility states, access keys, and the unique Google Cloud `store_id`.
3. **Bot_UI:** Handles all visual styling parameters (colors, themes, avatars, glassmorphism data) for the embeddable widgets.
4. **Documents:** Tracks metadata, safe filenames, and ingestion status for all knowledge base sources linked to specific bots.
5. **Scrapes:** Manages the status (pending/completed/failed), URLs, error logs, and page limits of asynchronous web scraping tasks.

## ⚙️ Local Setup & Installation

### 1. Clone the repository
```bash
git clone [https://github.com/TU7SHAR/bubbl.git](https://github.com/TU7SHAR/bubbl.git)
cd bubbl
pip -r install requirements.txt
python app.py
```

### 2. ENV SETUP
```
# Flask & Deployment
SECRET_KEY=your_secure_flask_key       
HOST_URL=http://127.0.0.1:5000          

# Database (PostgreSQL)
DATABASE_URL=postgresql://user:pass@host 

# AI & Scraping APIs
API_KEY=your_gemini_api_key           
FIRECRAWL_API_KEY=your_firecrawl_key     

# Communication (SMTP & Resend)    
EMAIL_ADDRESS=your_sender_email@gmail.com 
EMAIL_PASSWORD=your_google_app_password 
SUPPORT_EMAIL=admin@yourdomain.com     
OFFICE_LOCATION="Chandigarh, India"   
```

### 3. Database Initialization
```
# In a python terminal:
from app import app, db
with app.app_context():
    db.create_all()
```
