import re
from flask import Blueprint, request, jsonify, session
from bot.chat import get_response_from_gemini
from models.models import Bot, Lead, db
import logging 

api_bp = Blueprint('api_bp', __name__)

@api_bp.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    user_message = data.get('message')
    bot_id = data.get('bot_id') or session.get('active_bot_id')
    history = data.get('history', [])

    try:
        if not bot_id:
            reply = get_response_from_gemini(user_query=user_message, history=history)
            return jsonify({"response": reply})

        bot_record = Bot.query.get(bot_id)
        if not bot_record:
            return jsonify({"error": "Invalid Bot ID."})
        ai_prompt = bot_record.system_prompt or "You are a helpful assistant."
        timing = bot_record.lead_capture_timing
        if timing and timing != 'disabled':
            ai_prompt += "\n\n--- LEAD CAPTURE INSTRUCTIONS ---\n"
            ai_prompt += "Your secondary goal is to collect the user's Name, Email, and Phone Number.\n"
            if timing == 'start':
                ai_prompt += "Before answering their very first question, politely ask for their name, email address, and phone number.\n"
            elif timing == 'middle':
                ai_prompt += "After answering a question and providing value, politely ask for their name, email, and phone number to keep a record of the chat.\n"
            elif timing == 'end':
                ai_prompt += "When the conversation seems to be ending, politely ask for their name, email, and phone number.\n"
            ai_prompt += (
                "CRITICAL INSTRUCTION: Once the user provides their details, you MUST append this exact hidden tag at the VERY END of your response: "
                "[[LEAD: Name | Email | Phone]]\n"
                "Replace Name, Email, and Phone with their details. If they refuse to give a phone number, put 'None'. "
                "DO NOT acknowledge this tag in your conversational text (e.g., never say 'I have noted your details: [[LEAD...]]'). Just append it secretly at the very end of your response."
            )

        reply = get_response_from_gemini(
            user_query=user_message, 
            target_store_id=bot_record.store_id, 
            custom_prompt=ai_prompt,
            history=history
        )
        lead_match = re.search(r'\[\[LEAD:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\]\]', reply)
        if lead_match:
            extracted_name = lead_match.group(1).strip()
            extracted_email = lead_match.group(2).strip()
            extracted_phone = lead_match.group(3).strip()

            if extracted_phone.lower() == 'none':
                extracted_phone = ""
            new_lead = Lead(
                bot_id=bot_id, 
                name=extracted_name, 
                email=extracted_email, 
                phone=extracted_phone
            )
            db.session.add(new_lead)
            db.session.commit()
            reply = re.sub(r'\s*\[\[LEAD:.*?\]\]\s*', '', reply).strip()
        return jsonify({"response": reply})

    except Exception as e:
        db.session.rollback()
        logging.error(f"API Crash: {str(e)}")
        return jsonify({"error": "The AI is currently experiencing high demand. Please try again in a few seconds."})