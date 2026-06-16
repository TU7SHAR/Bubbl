import os
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types
from models.models import db, Bot

load_dotenv()

client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))

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
    "PUBLIC PLATFORM ROLE: You are the official public AI Assistant for our platform. Your name is 'Botlify Assistant'.\n"
    "Your ONLY job is to explain our website's services to visitors. "
    "Explain that we provide a platform where companies can upload PDFs or scrape URLs to create custom-trained AI chatbots. "
    "Keep answers brief and friendly. Do NOT attempt to answer specific company data questions. "
    "If they ask about specific data, tell them to 'Please Log In to access your organization's custom bot.' "
    "If they ask about pricing, respond with 'Our pricing is based on the number of documents you upload and the number of chatbot interactions. Please visit our pricing page.' "
    "If they ask about how to upload documents, respond with 'Once you create an account and log in, you can easily upload your documents through the dashboard.' "
    "If they ask some out of context question, respond with 'I'm here to help with questions about our platform and services. For other inquiries, please contact our support team.'"
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

        response = client.models.generate_content(
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