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

        if timing and timing != 'disabled' and timing != 'gatekeeper':
            ai_prompt += "\n\n--- LEAD CAPTURE INSTRUCTIONS ---\n"
            
            if timing.startswith('conv_'):
                ai_prompt += "Your goal is to collect the user's Name, Email, and Phone Number conversationally.\n"
                if 'start' in timing:
                    ai_prompt += "Before answering their first question, ask for their details.\n"
                elif 'middle' in timing:
                    ai_prompt += "After answering 1 or 2 questions, smoothly transition to ask for their details.\n"
                elif 'end' in timing:
                    ai_prompt += "When concluding the chat, ask for their details.\n"
                
                ai_prompt += (
                    "CRITICAL INSTRUCTION: Once the user provides their details, you MUST append this exact hidden tag at the VERY END of your response: "
                    "[[LEAD: Name | Email | Phone]]\n"
                    "Replace Name, Email, and Phone with their details. If they refuse to give a phone number, put 'None'. "
                    "DO NOT acknowledge this tag in your conversational text. Just append it secretly."
                )
                
            elif timing.startswith('form_'):
                ai_prompt += "You need to trigger a secure lead capture form.\n"
                if 'start' in timing:
                    ai_prompt += "On your VERY FIRST reply to the user, you MUST output the tag [SHOW_FORM].\n"
                elif 'middle' in timing:
                    ai_prompt += "After you have answered 1 or 2 questions, you MUST output the tag [SHOW_FORM].\n"
                elif 'end' in timing:
                    ai_prompt += "When concluding the chat, you MUST output the tag [SHOW_FORM].\n"
                
                ai_prompt += (
                    "CRITICAL INSTRUCTION: DO NOT ask the user to type their name or email in the chat. "
                    "Just include the exact text [SHOW_FORM] anywhere in your response (e.g. 'Please fill out this quick form: [SHOW_FORM]'), "
                    "and the system will automatically display the form for them."
                )

        reply = get_response_from_gemini(
            user_query=user_message, 
            target_store_id=bot_record.store_id, 
            custom_prompt=ai_prompt,
            history=history
        )

        # --- BACKEND INTERCEPTION (Only needed for Conversational mode) ---
        if timing and timing.startswith('conv_'):
            lead_match = re.search(r'\[\[LEAD:\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\]\]', reply)
            if lead_match:
                extracted_name = lead_match.group(1).strip()
                extracted_email = lead_match.group(2).strip()
                extracted_phone = lead_match.group(3).strip()

                if extracted_phone.lower() == 'none':
                    extracted_phone = ""

                new_lead = Lead(bot_id=bot_id, name=extracted_name, email=extracted_email, phone=extracted_phone)
                db.session.add(new_lead)
                db.session.commit()

                reply = re.sub(r'\s*\[\[LEAD:.*?\]\]\s*', '', reply).strip()

        return jsonify({"response": reply})

    except Exception as e:
        db.session.rollback()
        logging.error(f"API Crash: {str(e)}")
        return jsonify({"error": "The AI is currently experiencing high demand. Please try again in a few seconds."})
    
@api_bp.route('/api/lead', methods=['POST'])
def capture_lead():
    data = request.json
    bot_id = data.get('bot_id')
    name = data.get('name')
    email = data.get('email')
    phone = data.get('phone', '')

    if not bot_id or not name or not email:
        return jsonify({"error": "Missing required fields"}), 400

    try:
        new_lead = Lead(bot_id=bot_id, name=name, email=email, phone=phone)
        db.session.add(new_lead)
        db.session.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        db.session.rollback()
        logging.error(f"Lead Capture Database Error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500