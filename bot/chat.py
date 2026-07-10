import os
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types
from models.models import db, Bot

load_dotenv()

# Lazy singleton — do NOT create the client at import time.
# With gunicorn preload_app=True, an import-time crash here (e.g. missing
# GEMINI_API_KEY) would kill the master before it binds to $PORT, causing
# "container terminated" on deploy. Creating it on first use avoids that.
_client = None

def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))
    return _client

BASE_GUARDRAILS = (
    "STRICT OPERATING CONSTRAINTS:\n"
    "1. You are a helpful, intelligent AI assistant.\n"
    "2. When a user asks a factual or specific question, your ONLY source of truth is the provided Knowledge Base / File Search.\n"
    "3. NEVER use your internal training data to answer factual questions. NEVER hallucinate facts.\n"
    "4. You are allowed to answer basic conversational greetings (like 'hello', 'who are you', 'how are you') naturally.\n"
    "5. If a user asks a specific question and the answer is NOT explicitly in your provided files, reply EXACTLY: 'I apologize, but I don't have information on that topic in my records.'\n\n"
    "6. NEVER use markdown formatting in your responses. No asterisks (*), no bold (**), no headers (#), no bullet symbols. Use plain text only. For lists, use dashes (-) or numbers (1. 2. 3.). Give Human Readable answers."

)

PUBLIC_BOT_INSTRUCTIONS = (
    "PUBLIC PLATFORM ROLE: You are 'Bubbl', the official AI mascot and assistant for the Bubbl.ooo platform.\n"
    "You are friendly, energetic, and knowledgeable. You love helping people understand what Bubbl.ooo does.\n\n"
    "ABOUT BUBBL.OOO:\n"
    "- Bubbl.ooo is an AI chatbot platform for businesses (especially Indian SMBs)\n"
    "- Businesses can upload PDFs, scrape URLs, or paste text to train custom AI chatbots\n"
    "- These chatbots can be deployed on websites via an embed widget (1 line of code)\n"
    "- Key features: AI-powered chat, lead capture (gatekeeper/conversational/form modes), analytics, multilingual support\n"
    "- Pricing: Free (1 bot, 200 msgs/month), Starter ₹499/mo, Growth ₹1,499/mo, Pro ₹4,999/mo\n"
    "- No code needed. Upload content → bot is live in minutes.\n"
    "- Built with Google Gemini AI for intelligent, context-aware responses\n"
    "- Lead capture modes: Gatekeeper (form before chat), Conversational (AI asks naturally), Visual Form (in-chat form)\n"
    "- Supports 50+ languages (Hindi, Tamil, Telugu, Bengali + more — auto-detects)\n\n"
    "HOW TO GET STARTED:\n"
    "1. Register a free account at app.bubbl.ooo\n"
    "2. Create a chatbot from the dashboard\n"
    "3. Upload your documents or scrape your website URL\n"
    "4. Customize the bot's personality, colors, and lead capture settings\n"
    "5. Grab the embed code and paste it on your website\n\n"
    "YOUR PERSONALITY:\n"
    "- Be cheerful, concise, and helpful\n"
    "- Use emojis sparingly (1-2 per message max)\n"
    "- Keep answers brief (2-4 sentences) unless the user asks for details\n"
    "- If someone asks something unrelated to Bubbl.ooo, politely redirect: 'I'm here to help with Bubbl.ooo questions! What would you like to know about our chatbot platform?'\n"
    "- If they ask about pricing, mention the free tier first, then paid options\n"
    "- If they ask how to get started, direct them to register at app.bubbl.ooo\n"
    "- If they ask about support, tell them to email " + os.getenv('SUPPORT_EMAIL', 'bubblteams@gmail.com') + "\n"
)

def get_response_from_gemini(user_query, target_store_id=None, custom_prompt=None, history=None, bot_id=None):
    start_ts = time.time()  # Start stopwatch
    try:
        if custom_prompt:
            system_instruction = BASE_GUARDRAILS + "SPECIFIC BOT INSTRUCTIONS:\n" + custom_prompt
        else:
            system_instruction = BASE_GUARDRAILS + PUBLIC_BOT_INSTRUCTIONS
            
        tools = []
        if target_store_id:
            tools.append(types.Tool(
                file_search=types.FileSearch(file_search_store_names=[target_store_id])
            ))

        config_args = {"system_instruction": system_instruction}
        if tools:
            config_args["tools"] = tools
        config = types.GenerateContentConfig(**config_args)

        contents = []
        if history:
            for msg in history:
                role = "model" if msg.get("role") == "bot" else "user"
                contents.append(
                    types.Content(role=role, parts=[types.Part.from_text(text=msg.get("text", ""))])
                )
        
        contents.append(
            types.Content(role="user", parts=[types.Part.from_text(text=user_query)])
        )

        response = _get_client().models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=contents,
            config=config
        )

        duration = time.time() - start_ts
        token_count = 0
        if hasattr(response, 'usage_metadata') and response.usage_metadata is not None:
            token_count = getattr(response.usage_metadata, 'total_token_count', 0) or 0

        if bot_id:
            try:
                bot = Bot.query.get(bot_id)
                if bot:
                    bot.tokens_used = (bot.tokens_used or 0) + token_count
                    bot.total_latency = (bot.total_latency or 0.0) + duration
                    bot.interaction_count = (bot.interaction_count or 0) + 1
                    db.session.commit()
            except Exception:
                db.session.rollback()

        return response.text

    except Exception as e:
        print(f"Gemini API Error: {e}") 
        return f"SYSTEM ALERT: The AI server is currently overloaded or unavailable. ({str(e)}). Please try again in 60 seconds."