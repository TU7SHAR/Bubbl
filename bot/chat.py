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

# --- PUBLIC BOT: Personality + Button instructions ---
# This is used ALONGSIDE the RAG knowledge base (scraped site content).
# The factual info comes from the vector store; this just defines personality + button format.
# NOTE: Available links are injected dynamically from the platform bot's managed links (DB).
PUBLIC_BOT_PERSONALITY_BASE = (
    "PUBLIC PLATFORM ROLE: You are 'Bubbl', the official AI mascot and assistant for the Bubbl.ooo platform.\n"
    "You are friendly, energetic, and knowledgeable. You love helping people understand what Bubbl.ooo does.\n\n"
    "YOUR PERSONALITY:\n"
    "- Be cheerful, concise, and helpful\n"
    "- Use emojis sparingly (1-2 per message max)\n"
    "- Keep answers brief (2-4 sentences) unless the user asks for details\n"
    "- If someone asks something unrelated to Bubbl.ooo, politely redirect: 'I'm here to help with Bubbl.ooo questions! What would you like to know about our chatbot platform?'\n"
    "- If they ask about pricing, mention the free tier first, then paid options\n"
    "- If they ask how to get started, direct them to register at app.bubbl.ooo\n"
    "- If they ask about support, tell them to email " + os.getenv('SUPPORT_EMAIL', 'bubblteams@gmail.com') + "\n\n"
    "IMPORTANT: Answer questions using the information from your Knowledge Base (scraped site content).\n"
    "Your knowledge comes from the actual bubbl.ooo and app.bubbl.ooo websites.\n"
    "If something isn't in your knowledge base, say so honestly.\n\n"
    "INTERACTIVE BUTTONS (OPTIONAL):\n"
    "You MAY show clickable buttons below your message to help users navigate.\n"
    "Buttons are OPTIONAL — only use them when you're directing the user to a specific page.\n"
    "ALWAYS answer the question FIRST with full information, then optionally add buttons.\n"
    "Format: [[BUTTONS: category:Label|URL, category:Label|URL]]\n\n"
    "Available categories:\n"
    "- pricing (orange) — only for pricing page\n"
    "- action (green) — for sign up / register\n"
    "- info (blue) — for features or how-to\n"
    "- support (purple) — for contact/help\n"
    "- link (gray) — general links\n\n"
)

PUBLIC_BOT_BUTTON_RULES = (
    "BUTTON RULES:\n"
    "- ANSWER THE QUESTION FIRST. Buttons are a supplement, not a replacement.\n"
    "- Only show buttons if the user would genuinely benefit from visiting a page\n"
    "- Do NOT show buttons for greetings, casual chat, or when you already answered fully\n"
    "- Max 1-2 buttons per response\n"
    "- ONLY use URLs from the 'Available links' list above. NEVER invent or guess URLs.\n"
    "- If no link from the list is relevant, do NOT show any buttons.\n"
    "- The buttons tag must be the LAST thing in your response\n"
)


def _get_platform_bot_config():
    """
    Get the platform bot's store_id AND managed links.
    Returns (store_id, links_text) or (None, "") if not configured.
    """
    import json
    platform_bot = Bot.query.filter_by(bot_type='platform').first()
    if platform_bot and platform_bot.store_id:
        # Links are stored as JSONB in custom_form_fields
        links_text = ""
        raw = platform_bot.custom_form_fields or []
        if raw:
            try:
                links = raw if isinstance(raw, list) else json.loads(raw)
                if isinstance(links, list):
                    for link in links:
                        label = link.get('label', '')
                        url = link.get('url', '')
                        category = link.get('category', 'link')
                        if label and url:
                            links_text += f"- {url} — {label} (category: {category})\n"
            except (json.JSONDecodeError, TypeError):
                pass
        return platform_bot.store_id, links_text

    # Env var fallback
    public_bot_id = os.getenv('PUBLIC_BOT_ID')
    if not public_bot_id:
        return None, ""
    try:
        bot = Bot.query.get(int(public_bot_id))
        if bot and bot.store_id:
            return bot.store_id, ""
    except (ValueError, TypeError):
        pass
    return None, ""


def _build_public_bot_prompt(links_text=""):
    """Build the full public bot system prompt with dynamic links."""
    prompt = PUBLIC_BOT_PERSONALITY_BASE
    if links_text:
        prompt += "Available links (ONLY use these, do NOT invent URLs):\n"
        prompt += links_text + "\n"
    else:
        prompt += "Available links: NONE configured. Do NOT show any buttons.\n\n"
    prompt += PUBLIC_BOT_BUTTON_RULES
    return prompt


def get_response_from_gemini(user_query, target_store_id=None, custom_prompt=None, history=None, bot_id=None):
    start_ts = time.time()  # Start stopwatch
    try:
        if custom_prompt:
            system_instruction = BASE_GUARDRAILS + "SPECIFIC BOT INSTRUCTIONS:\n" + custom_prompt
        else:
            # --- DYNAMIC PUBLIC BOT ---
            # Check if a platform bot is configured (scraped site content)
            public_store_id, links_text = _get_platform_bot_config()
            if public_store_id:
                # Build prompt with dynamic links from admin panel
                system_instruction = BASE_GUARDRAILS + _build_public_bot_prompt(links_text)
                target_store_id = public_store_id  # Feed the scraped content as RAG
            else:
                # Fallback: no scrape configured yet
                system_instruction = BASE_GUARDRAILS + _build_public_bot_prompt("")
            
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