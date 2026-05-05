import re
from flask import Blueprint, request, jsonify, session
from bot.chat import get_response_from_gemini
from models.models import Bot, Lead, db
import logging 
import json

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
        custom_fields = getattr(bot_record, 'custom_form_fields', '').strip()

        # --- DYNAMIC PROMPT INJECTION ---
        if timing and timing != 'disabled' and timing != 'gatekeeper':
            ai_prompt += "\n\n--- LEAD CAPTURE INSTRUCTIONS ---\n"
            
            # Extract just the field names from the JSON format (if present)
            custom_field_names = []
            if custom_fields:
                try:
                    fields_list = json.loads(custom_fields)
                    custom_field_names = [f.get('name') for f in fields_list if f.get('name')]
                except:
                    pass

            custom_text_str = ", ".join(custom_field_names)
            custom_text = f", and these extra details: {custom_text_str}" if custom_text_str else ""
            
            # RULES FOR CONVERSATIONAL MODE
            if timing.startswith('conv_'):
                ai_prompt += f"Your goal is to collect the user's Name, Email, Phone Number{custom_text} conversationally. Ask for the information naturally.\n"
                
                if 'start' in timing:
                    ai_prompt += f"Before answering their very first question, politely ask for their name, email, phone number{custom_text}.\n"
                elif 'middle' in timing:
                    ai_prompt += f"After answering 1 or 2 questions, smoothly transition to ask for their name, email, phone number{custom_text}.\n"
                elif 'end' in timing:
                    ai_prompt += f"When concluding the chat, politely ask for their name, email, phone number{custom_text}.\n"

                # NEW STRICT VALIDATION & SCORING RULES
                ai_prompt += (
                    "CRITICAL VALIDATION & SCORING:\n"
                    "1. STRICT DATA ENFORCEMENT: Do NOT accept gibberish (e.g., 'asdf', 'test'), fake short emails ('a@m.com'), or impossibly short phone numbers (e.g., '978'). If the user provides fake or lazy data, politely tell them it seems invalid and ask for their real details to proceed.\n"
                    "2. LEAD SCORING: You must secretly evaluate this user's intent. Score them 'High' (asking deep questions, providing full details), 'Medium' (normal interaction), or 'Low' (giving short, dismissive, or borderline fake answers).\n\n"
                    "CRITICAL INSTRUCTION: Once the user provides ALL valid details, you MUST append this exact hidden tag at the VERY END of your response: "
                    "[[LEAD: Name | Email | Phone | JSON_Custom_Data]]\n"
                    "Replace JSON_Custom_Data with a valid JSON object containing any extra details AND your Lead Quality Score under the key 'Priority' (e.g. {\"Company\": \"Google\", \"Priority\": \"High\"}). If there are no extra details, just put {\"Priority\": \"Low/Medium/High\"}. "
                    "DO NOT acknowledge this tag in your conversational text. Just append it secretly."
                )
                
            # RULES FOR IN-CHAT FORM MODE
            elif timing.startswith('form_'):
                ai_prompt += "You need to trigger a secure visual lead capture form.\n"
                if 'start' in timing:
                    ai_prompt += "On your VERY FIRST reply to the user, you MUST output the tag [SHOW_FORM].\n"
                elif 'middle' in timing:
                    ai_prompt += "After you have answered 1 or 2 questions, you MUST output the tag [SHOW_FORM].\n"
                elif 'end' in timing:
                    ai_prompt += "When concluding the chat, you MUST output the tag [SHOW_FORM].\n"
                
                ai_prompt += (
                    "CRITICAL INSTRUCTION: DO NOT ask the user to type their name or email in the chat. "
                    "Simply include the exact text [SHOW_FORM] anywhere in your response (e.g. 'Please fill out this form: [SHOW_FORM]'), "
                    "and the system will display the visual form."
                )

        # Send to Gemini
        reply = get_response_from_gemini(
            user_query=user_message, 
            target_store_id=bot_record.store_id, 
            custom_prompt=ai_prompt,
            history=history
        )

        # --- BACKEND INTERCEPTION ---
        if timing and timing.startswith('conv_'):
            lead_match = re.search(r'\[\[LEAD:(.*?)\]\]', reply)
            if lead_match:
                extracted_content = lead_match.group(1)
                parts = [p.strip() for p in extracted_content.split('|')]
                
                extracted_name = parts[0] if len(parts) > 0 else "Unknown"
                extracted_email = parts[1] if len(parts) > 1 else "Unknown"
                extracted_phone = parts[2] if len(parts) > 2 else ""
                extracted_custom_raw = parts[3] if len(parts) > 3 else "{}"

                if extracted_phone.lower() == 'none':
                    extracted_phone = ""
                    
                custom_data_dict = {}
                try:
                    custom_data_dict = json.loads(extracted_custom_raw)
                except Exception:
                    if extracted_custom_raw and extracted_custom_raw != '{}':
                        custom_data_dict = {"Extracted Data": extracted_custom_raw}

                new_lead = Lead(
                    bot_id=bot_id, 
                    name=extracted_name, 
                    email=extracted_email, 
                    phone=extracted_phone,
                    custom_data=custom_data_dict
                )
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
    custom_data = data.get('custom_data', {}) 

    if not bot_id or not name or not email:
        return jsonify({"error": "Missing required fields"}), 400

    try:
        new_lead = Lead(
            bot_id=bot_id, 
            name=name, 
            email=email, 
            phone=phone, 
            custom_data=custom_data 
        )
        db.session.add(new_lead)
        db.session.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        db.session.rollback()
        logging.error(f"Lead Capture Database Error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500