from flask import Blueprint, request, jsonify, session
from bot.chat import get_response_from_gemini
from models.models import Bot, Lead, db
import logging 

api_bp = Blueprint('api_bp', __name__)

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
        return jsonify({"error": "Internal server error while saving lead."}), 500

@api_bp.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    user_message = data.get('message')
    
    bot_id = data.get('bot_id') 
    if not bot_id and 'active_bot_id' in session:
        bot_id = session.get('active_bot_id')

    try:
        if bot_id:
            bot_record = Bot.query.get(bot_id)
            if bot_record:
                reply = get_response_from_gemini(
                    user_query=user_message, 
                    target_store_id=bot_record.store_id, 
                    custom_prompt=bot_record.system_prompt
                )
            else:
                return jsonify({"error": "Invalid Bot ID."})
                
        else:
            reply = get_response_from_gemini(
                user_query=user_message, 
                target_store_id=None, 
                custom_prompt=None
            )
            
        return jsonify({"response": reply})

    except Exception as e:
        logging.error(f"Gemini API Crash: {str(e)}")
        return jsonify({
            "error": "The AI is currently experiencing high demand. Please try again in a few seconds."
        })