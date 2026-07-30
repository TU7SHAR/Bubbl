import json
import re
import logging
from flask import Blueprint, request, jsonify, session, current_app
from bot.chat import get_response_from_gemini
from models.models import Bot, Lead, ChatMessage, db
from extensions import limiter, cache
from utils.plan_limits import check_message_limit, increment_message_count
import uuid

api_bp = Blueprint('api_bp', __name__)


def _build_user_context():
    """
    Build a context string about the current logged-in user.
    Injected into the AI prompt so the bot can answer personalized questions
    like "what plan am I on?" or "how many leads do I have?".
    
    Returns empty string for anonymous/embed users (no session).
    """
    user_id = session.get('user_id')
    if not user_id or user_id == -1:  # -1 = super admin
        return ""
    
    try:
        from models.models import User, Organization, Bot as BotModel
        
        user = User.query.get(user_id)
        org = Organization.query.get(session.get('org_id'))
        
        if not user or not org:
            return ""
        
        # Query real-time stats
        bot_count = BotModel.query.filter_by(org_id=org.id).count()
        lead_count = Lead.query.join(BotModel).filter(BotModel.org_id == org.id).count()
        messages_used = org.messages_used or 0
        
        # Plan limits
        from utils.plan_limits import PLAN_LIMITS
        limits = PLAN_LIMITS.get(org.plan or 'free', PLAN_LIMITS['free'])
        messages_limit = limits.get('messages', 200)
        bots_limit = limits.get('bots', 1)
        
        context = (
            "\n--- CURRENT USER CONTEXT (use this for personalized questions) ---\n"
            f"- Logged in: Yes\n"
            f"- Name: {user.name}\n"
            f"- Email: {user.email}\n"
            f"- Organization: {org.name}\n"
            f"- Plan: {org.plan or 'free'}\n"
            f"- Messages used: {messages_used}/{messages_limit} this month\n"
            f"- Bots created: {bot_count}/{bots_limit}\n"
            f"- Leads captured: {lead_count}\n"
            f"- Account verified: {user.is_verified}\n"
            "- If the user asks about their account, plan, usage, or personal info, use THIS data.\n"
            "- Do NOT share this info unless the user specifically asks.\n"
            "--- END USER CONTEXT ---\n\n"
        )
        return context
    except Exception as e:
        logging.warning(f"[context_injection] Failed to build user context: {e}")
        return ""


def _client_ip():
    """Extract the real client IP, honoring nginx's X-Forwarded-For header."""
    try:
        xff = request.headers.get('X-Forwarded-For', '')
        if xff:
            return xff.split(',')[0].strip()[:45]
        return (request.remote_addr or '')[:45]
    except Exception:
        return None


def _save_chat_message(bot_id, session_id, role, content, lead_id=None, tokens_used=0, ip_address=None):
    """Persist a single chat message to the database (fire-and-forget)."""
    try:
        msg = ChatMessage(
            bot_id=bot_id,
            session_id=session_id,
            role=role,
            content=content[:5000] if content else "",  # Cap at 5000 chars
            lead_id=lead_id,
            tokens_used=tokens_used,
            ip_address=ip_address,
        )
        db.session.add(msg)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logging.warning(f"[chat_persist] Failed to save message: {e}")


def get_bot_config(bot_id):
    """
    Returns a bot's chat config as a plain dict, cached for 60s.

    We cache a DICT (not the SQLAlchemy object) on purpose: caching an ORM
    object across requests causes DetachedInstanceError because its DB session
    is closed. A plain dict is safe to reuse.

    The cache is invalidated in bot_management.py whenever a bot is
    updated/renamed/deleted, so edits show up immediately.
    """
    cache_key = f"bot_config_{bot_id}"
    cfg = cache.get(cache_key)
    if cfg is None:
        bot = Bot.query.get(bot_id)
        if not bot:
            cfg = {"exists": False}
        else:
            cfg = {
                "exists": True,
                "system_prompt": bot.system_prompt,
                "lead_capture_timing": bot.lead_capture_timing,
                "custom_form_fields": getattr(bot, "custom_form_fields", []) or [],
                "store_id": bot.store_id,
            }
        cache.set(cache_key, cfg, timeout=60)
    return cfg


def sanitize_custom_data(raw_dict, field_schema_json=""):
    """
    Post-process the LLM-generated custom_data dict before writing to DB.
    - Normalises key casing to Title Case so template matching is reliable.
    - Coerces 'number'-typed fields to plain integers (strips currency, units, k/lakh/crore).
    - Drops null-ish values so the table shows '-' instead of 'None'/'null'/''.
    - Preserves 'Priority' exactly.
    """
    if not raw_dict or not isinstance(raw_dict, dict):
        return {}

    # Build a name → type map from the bot's field schema (best-effort)
    field_types = {}
    if field_schema_json:
        try:
            for f in json.loads(field_schema_json):
                name = f.get('name', '')
                if name:
                    field_types[name.lower()] = f.get('type', 'text')
        except Exception:
            pass

    def coerce_number(val):
        """Strip non-numeric noise and return an int string, or the original if hopeless."""
        if val is None:
            return "0"
        s = str(val).strip().lower()
        # Named multipliers — longer/more-specific patterns first
        multipliers = [
            (r'(\d+(?:\.\d+)?)\s*cr(?:ore)?',           1_00_00_000),
            (r'(\d+(?:\.\d+)?)\s*billion',               1_000_000_000),
            (r'(\d+(?:\.\d+)?)\s*million',               1_000_000),
            (r'(\d+(?:\.\d+)?)\s*(?:lakh|lac(?:s|h)?)',  1_00_000),
            (r'(\d+(?:\.\d+)?)\s*thousand',              1_000),
            (r'(\d+(?:\.\d+)?)\s*k\b',                   1_000),
            (r'(\d+(?:\.\d+)?)\s*l\b',                   1_00_000),   # bare 'l' last
        ]
        for pattern, mult in multipliers:
            m = re.search(pattern, s)
            if m:
                return str(int(float(m.group(1)) * mult))
        # Strip everything except digits, dots, hyphens; take lower bound of ranges
        s = re.sub(r'[^\d.\-]', '', s)
        if '-' in s:
            s = s.split('-')[0]   # "10000-20000" → "10000"
        try:
            return str(int(float(s))) if s else "0"
        except ValueError:
            return "0"

    cleaned = {}
    for key, value in raw_dict.items():
        # Keep Priority untouched
        if key == 'Priority':
            cleaned['Priority'] = value
            continue

        # Drop empty / null-ish values
        if value is None or str(value).strip().lower() in ('', 'none', 'null', 'n/a', 'not provided', '-'):
            continue

        # Normalise key to Title Case
        clean_key = key.strip().title()

        # Coerce number fields
        if field_types.get(key.lower()) == 'number':
            cleaned[clean_key] = coerce_number(value)
        else:
            cleaned[clean_key] = str(value).strip()

    return cleaned

@api_bp.route('/api/chat', methods=['POST'])
@limiter.limit("20 per minute")  # Protects Gemini API spend
def chat():
    data = request.json
    user_message = data.get('message')
    bot_id = data.get('bot_id') or session.get('active_bot_id')
    history = data.get('history', [])
    chat_session_id = data.get('session_id') or session.get('chat_session_id') or str(uuid.uuid4())

    # Store session_id in Flask session for continuity
    if 'chat_session_id' not in session:
        session['chat_session_id'] = chat_session_id

    try:
        if not bot_id:
            # --- CONTEXT INJECTION for public bot ---
            user_context = _build_user_context()
            reply = get_response_from_gemini(user_query=user_message, history=history, custom_prompt=user_context if user_context else None)
            # Save public bot conversation
            _save_chat_message(bot_id=None, session_id=chat_session_id, role='user', content=user_message, ip_address=_client_ip())
            _save_chat_message(bot_id=None, session_id=chat_session_id, role='bot', content=reply)
            return jsonify({"response": reply, "session_id": chat_session_id})

        bot_cfg = get_bot_config(bot_id)
        if not bot_cfg["exists"]:
            return jsonify({"error": "Invalid Bot ID."})

        # --- PLAN LIMIT CHECK ---
        # Find which org owns this bot to check their message quota
        from models.models import Bot as BotModel
        bot_record = BotModel.query.get(bot_id)
        if bot_record:
            allowed, remaining, limit = check_message_limit(bot_record.org_id)
            if not allowed:
                return jsonify({"response": "I'm currently unavailable as this bot's message limit has been reached for this month. Please try again later or contact the website owner for assistance.", "lead_id": None})

        ai_prompt = bot_cfg["system_prompt"] or "You are a helpful assistant."
        
        # --- CONTEXT INJECTION: Add user session data so bot can answer personal questions ---
        user_context = _build_user_context()
        if user_context:
            ai_prompt = user_context + ai_prompt
        
        timing = bot_cfg["lead_capture_timing"]
        custom_fields = bot_cfg["custom_form_fields"] or []
        # Ensure it's a JSON string for the prompt builder (legacy compat)
        if isinstance(custom_fields, list):
            custom_fields = json.dumps(custom_fields)
        custom_fields = custom_fields.strip() if isinstance(custom_fields, str) else ""

        if timing and timing != 'disabled' and timing != 'gatekeeper':
            ai_prompt += "\n\n--- LEAD CAPTURE INSTRUCTIONS ---\n"
            
            custom_field_names = []
            formatting_rules = ""
            
            if custom_fields:
                try:
                    fields_list = json.loads(custom_fields)
                    for f in fields_list:
                        name = f.get('name')
                        f_type = f.get('type', 'text')
                        
                        if name:
                            custom_field_names.append(name)
                            if f_type == 'number':
                                # STRICT NUMERIC ENFORCEMENT
                                formatting_rules += (
                                    f"  * {name} (STRICT NUMERIC): You are FORBIDDEN from including any text, units, or currency symbols. "
                                    f"Values like '10000inr', '10k', or 'Rs 500' are SYSTEM FAILURES. Output raw digits ONLY (e.g., 10000). "
                                    f"Convert '1 crore' to 10000000. If the user provides a range, use the LOWER BOUND. If unknown, use 0.\n"
                                )
                            elif f_type == 'email':
                                formatting_rules += f"  * {name}: MUST be a standard, lowercase email address (e.g., name@domain.com).\n"
                except Exception:
                    pass

            custom_text_str = ", ".join(custom_field_names)
            custom_text = f", and these extra details: {custom_text_str}" if custom_text_str else ""
            
            if timing.startswith('conv_'):
                ai_prompt += f"Your goal is to collect the user's Name, Email, Phone Number{custom_text} conversationally. Ask for the information naturally.\n"
                
                if 'start' in timing:
                    ai_prompt += f"Before answering their very first question, politely ask for their name, email, phone number{custom_text}.\n"
                elif 'middle' in timing:
                    ai_prompt += f"After answering 1 or 2 questions, smoothly transition to ask for their name, email, phone number{custom_text}.\n"
                elif 'end' in timing:
                    ai_prompt += f"When concluding the chat, politely ask for their name, email, phone number{custom_text}.\n"

                # STRICT VALIDATION & SCORING RULES
                ai_prompt += "\n### CRITICAL DATA INTEGRITY RULES (STRICT ENFORCEMENT):\n"
                ai_prompt += "1. RUTHLESS FAKE DATA REJECTION: You are a gatekeeper for high-quality data. Immediately reject and politely challenge placeholders ('asdf', 'test@test.com', '1234567890', 'user'). Do not generate the [[LEAD]] tag for fakes. Country Code is Optional not neccessary.\n"
                
                if formatting_rules:
                    ai_prompt += f"2. FORMATTING PROTOCOL:\n{formatting_rules}"
                    ai_prompt += "3. NO EXTRA TEXT IN TAGS: Do not add notes, currency symbols, or units inside the JSON_Custom_Data values. Integers must be pure numbers.\n\n"
                else:
                    ai_prompt += "2. LEAD SCORING: You must secretly evaluate this user's intent. Score them 'High', 'Medium', or 'Low' based on interaction quality.\n\n"
                
                ai_prompt += (
                    "FINAL INSTRUCTION: Only output the exact hidden tag ONLY ONCE during the entire conversation, immediately after the user provides their final verified missing detail. Do NOT output it again in subsequent messages.\n"
                    "The tag format is: [[LEAD: Name | Email | Phone | JSON_Custom_Data]]\n"
                    "Replace JSON_Custom_Data with a valid JSON object containing any extra details AND your Lead Quality Score under the key 'Priority' (e.g. {\"Company\": \"Google\", \"Priority\": \"High\"}). If there are no extra details, just put {\"Priority\": \"Low/Medium/High\"}. "
                    "DO NOT acknowledge this tag in your conversational text. Just append it secretly."
                )
                
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
                
        # --- This executes safely for all bots regardless of lead capture settings ---
        # Inject managed links (clickable buttons) into the bot's prompt
        from bot.chat import _build_links_text, BUTTON_INSTRUCTIONS
        bot_links = bot_record.managed_links if bot_record else []
        if bot_links:
            links_text = _build_links_text(bot_links)
            ai_prompt += "\n\n" + BUTTON_INSTRUCTIONS
            ai_prompt += "Available links (ONLY use these):\n" + links_text

        reply = get_response_from_gemini(
            user_query=user_message, 
            target_store_id=bot_cfg["store_id"], 
            custom_prompt=ai_prompt,
            history=history,
            bot_id=bot_id
        )

        lead_id = None # Initialize lead_id
        if timing and timing.startswith('conv_'):
            lead_match = re.search(r'\[\[LEAD:(.*?)\]\]', reply)
            if lead_match:
                extracted_content = lead_match.group(1)
                parts = [p.strip() for p in extracted_content.split('|')]
                
                extracted_name = parts[0] if len(parts) > 0 else "Unknown"
                extracted_email = parts[1] if len(parts) > 1 else "Unknown"
                extracted_phone = parts[2] if len(parts) > 2 else ""
                extracted_custom_raw = parts[3] if len(parts) > 3 else "{}"

                custom_data_dict = {}
                try:
                    custom_data_dict = json.loads(extracted_custom_raw)
                except Exception:
                    custom_data_dict = {"Extracted Data": extracted_custom_raw}

                # Sanitize: normalise keys, coerce numbers, drop empties
                custom_data_dict = sanitize_custom_data(custom_data_dict, custom_fields)

                existing_lead = Lead.query.filter_by(bot_id=bot_id, email=extracted_email).first()

                if existing_lead:
                    existing_lead.name = extracted_name
                    existing_lead.phone = extracted_phone
                    merged_custom = existing_lead.custom_data or {}
                    merged_custom.update(custom_data_dict)
                    existing_lead.custom_data = merged_custom
                    db.session.commit()
                    lead_id = existing_lead.id # Capture existing ID
                else:
                    new_lead = Lead(
                        bot_id=bot_id, 
                        name=extracted_name, 
                        email=extracted_email, 
                        phone=extracted_phone,
                        custom_data=custom_data_dict
                    )
                    db.session.add(new_lead)
                    db.session.commit()
                    lead_id = new_lead.id # Capture new ID

                reply = re.sub(r'\s*\[\[LEAD:.*?\]\]\s*', '', reply).strip()

        # Return lead_id so frontend can store it
        # Increment message count for the org
        if bot_record:
            increment_message_count(bot_record.org_id)

        # --- PERSIST CHAT TO DB ---
        _save_chat_message(bot_id=bot_id, session_id=chat_session_id, role='user', content=user_message, ip_address=_client_ip())
        _save_chat_message(bot_id=bot_id, session_id=chat_session_id, role='bot', content=reply, lead_id=lead_id)

        return jsonify({"response": reply, "lead_id": lead_id, "session_id": chat_session_id})

    except Exception as e:
        db.session.rollback()
        logging.error(f"API Crash: {str(e)}")
        return jsonify({"error": "The AI is currently experiencing high demand."})

@api_bp.route('/api/lead', methods=['POST'])
@limiter.limit("10 per minute")  # Prevents lead spam
def capture_lead():
    data = request.json
    bot_id = data.get('bot_id')
    name = data.get('name')
    email = data.get('email')
    phone = data.get('phone', '')
    custom_data = data.get('custom_data', {}) 

    if not bot_id or not name or not email:
        return jsonify({"error": "Missing required fields"}), 400

    # --- INPUT SANITIZATION (prevents prompt injection) ---
    # Strip characters that could manipulate AI instructions
    def sanitize_for_prompt(value, max_len=200):
        """Remove prompt-injection patterns from user input before interpolating into AI prompt."""
        if not value:
            return ""
        s = str(value)[:max_len]  # Length cap
        # Remove patterns that could manipulate AI behavior
        injection_patterns = [
            'ignore previous', 'ignore above', 'disregard',
            'new instructions', 'system:', 'assistant:',
            'you are now', 'forget everything', 'override',
            '[[', ']]', '{{', '}}',
        ]
        s_lower = s.lower()
        for pattern in injection_patterns:
            if pattern in s_lower:
                s = s.replace(pattern, '').replace(pattern.upper(), '').replace(pattern.title(), '')
        # Strip control characters and excessive whitespace
        s = re.sub(r'[\x00-\x1f\x7f]', '', s)
        s = re.sub(r'\s{3,}', ' ', s).strip()
        return s

    safe_name = sanitize_for_prompt(name, max_len=100)
    safe_email = sanitize_for_prompt(email, max_len=120)
    safe_phone = sanitize_for_prompt(phone, max_len=20)
    # Custom data: sanitize each value, limit total size
    safe_custom = {}
    if isinstance(custom_data, dict):
        for k, v in list(custom_data.items())[:10]:  # Max 10 fields
            safe_custom[sanitize_for_prompt(k, 50)] = sanitize_for_prompt(str(v), 200)

    try:
        validation_prompt = f"""
        You are a strict data validator for a lead capture form.
        Evaluate this form submission:
        Name: {safe_name}
        Email: {safe_email}
        Phone: {safe_phone}
        Custom Data: {safe_custom}
        
        1. Check for obvious fakes, gibberish, or placeholders ('asdf', 'email@gmail.com', '1234567890', 'test', 'user').
        2. Score the intent. High (real, professional), Medium (standard data), Low (lazy/placeholder).
        
        You MUST output ONLY a valid JSON object. No markdown, no backticks, no other text:
        {{"Priority": "High", "is_fake": false}}
        """
        
        ai_eval = get_response_from_gemini(user_query="Validate Form", custom_prompt=validation_prompt)
        
        try:
            clean_eval = ai_eval.replace('```json', '').replace('```', '').strip()
            score_data = json.loads(clean_eval)
            priority = score_data.get("Priority", "Medium")
            is_fake = score_data.get("is_fake", False)
        except Exception:
            priority = "Medium"
            is_fake = False
            
        if is_fake:
            return jsonify({"error": "Please provide valid, real contact details. Placeholders are not accepted."}), 400
            
        custom_data['Priority'] = priority

        # Sanitize keys and values before writing to DB
        # We don't have the bot's field schema here, but key normalisation still helps
        custom_data = sanitize_custom_data(custom_data)

        existing_lead = Lead.query.filter_by(bot_id=bot_id, email=email).first()
        lead_id = None

        if existing_lead:
            existing_lead.name = name
            existing_lead.phone = phone
            merged_custom = existing_lead.custom_data or {}
            merged_custom.update(custom_data)
            existing_lead.custom_data = merged_custom
            db.session.commit()
            lead_id = existing_lead.id
        else:
            new_lead = Lead(
                bot_id=bot_id, 
                name=name, 
                email=email, 
                phone=phone, 
                custom_data=custom_data 
            )
            db.session.add(new_lead)
            db.session.commit()
            lead_id = new_lead.id
            
        return jsonify({"success": True, "lead_id": lead_id}), 200

    except Exception as e:
        db.session.rollback()
        logging.error(f"Lead Capture Database Error: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500



@api_bp.route('/api/rate_message', methods=['POST'])
def rate_message():
    """Rate a bot response (thumbs up/down). Called from the chat widget."""
    data = request.json or {}
    session_id = data.get('session_id')
    message_index = data.get('message_index')  # which bot message (0-indexed) in the session
    rating = data.get('rating')  # 1 or -1

    if not session_id or message_index is None or rating not in (1, -1):
        return jsonify({"error": "Invalid request."}), 400

    # Find the Nth bot message in this session
    bot_messages = ChatMessage.query.filter_by(
        session_id=session_id, role='bot'
    ).order_by(ChatMessage.created_at.asc()).all()

    if message_index >= len(bot_messages) or message_index < 0:
        return jsonify({"error": "Message not found."}), 404

    msg = bot_messages[message_index]
    msg.rating = rating
    db.session.commit()

    return jsonify({"success": True, "message_id": msg.id, "rating": rating})
