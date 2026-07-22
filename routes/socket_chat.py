# =========================================
# WEBSOCKET CHAT — BUBBL.OOO
# =========================================
# Real-time chat using Flask-SocketIO.
# Streams AI responses word-by-word to the client via WebSocket events.
#
# Events:
#   Client → Server:  'chat_message' { message, bot_id, history, session_id }
#   Server → Client:  'chat_chunk'   { text }          (partial response, streamed)
#   Server → Client:  'chat_complete' { response, lead_id, session_id }
#   Server → Client:  'chat_error'   { error }

import json
import re
import os
import time
import uuid
import logging
from flask import request
from flask_socketio import emit

from models.models import Bot, Lead, ChatMessage, db
from extensions import cache
from utils.plan_limits import check_message_limit, increment_message_count
from bot.chat import (
    BASE_GUARDRAILS, _get_client, _get_platform_bot_config,
    _build_public_bot_prompt, _build_links_text, BUTTON_INSTRUCTIONS
)
from google.genai import types


def register_socket_events(socketio):
    """Register all WebSocket event handlers with the SocketIO instance."""

    @socketio.on('chat_message')
    def handle_chat_message(data):
        """
        Main chat handler — receives a message, streams the AI response
        chunk by chunk, then emits a final 'chat_complete' event.
        """
        user_message = data.get('message', '').strip()
        bot_id = data.get('bot_id') or None
        history = data.get('history', [])
        chat_session_id = data.get('session_id') or str(uuid.uuid4())

        if not user_message:
            emit('chat_error', {'error': 'Empty message'})
            return

        try:
            # --- BUILD THE PROMPT ---
            target_store_id = None
            system_instruction = None

            if not bot_id:
                # Public platform bot
                public_store_id, links_text = _get_platform_bot_config()
                if public_store_id:
                    system_instruction = BASE_GUARDRAILS + _build_public_bot_prompt(links_text)
                    target_store_id = public_store_id
                else:
                    system_instruction = BASE_GUARDRAILS + _build_public_bot_prompt("")
            else:
                # Specific bot
                bot_cfg = _get_bot_config_for_ws(bot_id)
                if not bot_cfg or not bot_cfg.get("exists"):
                    emit('chat_error', {'error': 'Invalid Bot ID.'})
                    return

                # Plan limit check
                bot_record = Bot.query.get(bot_id)
                if bot_record:
                    allowed, remaining, limit = check_message_limit(bot_record.org_id)
                    if not allowed:
                        emit('chat_complete', {
                            'response': "I'm currently unavailable as this bot's message limit has been reached for this month.",
                            'lead_id': None,
                            'session_id': chat_session_id
                        })
                        return

                target_store_id = bot_cfg.get("store_id")
                ai_prompt = bot_cfg.get("system_prompt") or "You are a helpful assistant."
                
                timing = bot_cfg.get("lead_capture_timing")
                custom_fields = bot_cfg.get("custom_form_fields") or []

                if isinstance(custom_fields, list):
                    custom_fields = json.dumps(custom_fields)
                custom_fields = custom_fields.strip() if isinstance(custom_fields, str) else ""

                # Build lead capture instructions (same logic as api.py)
                ai_prompt = _build_lead_capture_prompt(ai_prompt, timing, custom_fields)

                # Inject managed links
                if bot_record and bot_record.managed_links:
                    links_text = _build_links_text(bot_record.managed_links)
                    ai_prompt += "\n\n" + BUTTON_INSTRUCTIONS
                    ai_prompt += "Available links (ONLY use these):\n" + links_text

                system_instruction = BASE_GUARDRAILS + "SPECIFIC BOT INSTRUCTIONS:\n" + ai_prompt

            # --- PREPARE GEMINI REQUEST ---
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
                types.Content(role="user", parts=[types.Part.from_text(text=user_message)])
            )

            # --- STREAM THE RESPONSE ---
            start_ts = time.time()
            full_response = ""

            stream = _get_client().models.generate_content_stream(
                model="gemini-3.1-flash-lite-preview",
                contents=contents,
                config=config
            )

            for chunk in stream:
                if chunk.text:
                    full_response += chunk.text
                    emit('chat_chunk', {'text': chunk.text})

            duration = time.time() - start_ts

            # --- TOKEN TRACKING ---
            token_count = 0
            if hasattr(stream, 'usage_metadata') and stream.usage_metadata:
                token_count = getattr(stream.usage_metadata, 'total_token_count', 0) or 0

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

            # --- LEAD EXTRACTION ---
            lead_id = None
            reply = full_response

            if bot_id and bot_cfg.get("lead_capture_timing", "").startswith('conv_'):
                lead_match = re.search(r'\[\[LEAD:(.*?)\]\]', reply)
                if lead_match:
                    lead_id = _extract_and_save_lead(lead_match, bot_id, custom_fields)
                    reply = re.sub(r'\s*\[\[LEAD:.*?\]\]\s*', '', reply).strip()

            # --- INCREMENT MESSAGE COUNT ---
            if bot_id and bot_record:
                increment_message_count(bot_record.org_id)

            # --- PERSIST CHAT ---
            _save_ws_chat_message(bot_id, chat_session_id, 'user', user_message)
            _save_ws_chat_message(bot_id, chat_session_id, 'bot', reply, lead_id=lead_id, tokens_used=token_count)

            # --- EMIT FINAL COMPLETE EVENT ---
            emit('chat_complete', {
                'response': reply,
                'lead_id': lead_id,
                'session_id': chat_session_id
            })

        except Exception as e:
            db.session.rollback()
            logging.error(f"[ws] Chat error: {str(e)}")
            emit('chat_error', {'error': 'The AI is currently experiencing high demand. Please try again.'})


# ═══════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════

def _get_bot_config_for_ws(bot_id):
    """Get bot config (cached dict) — same as api.py's get_bot_config."""
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


def _save_ws_chat_message(bot_id, session_id, role, content, lead_id=None, tokens_used=0):
    """Persist a chat message to DB."""
    try:
        msg = ChatMessage(
            bot_id=bot_id,
            session_id=session_id,
            role=role,
            content=content[:5000] if content else "",
            lead_id=lead_id,
            tokens_used=tokens_used,
        )
        db.session.add(msg)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logging.warning(f"[ws_chat_persist] Failed to save message: {e}")


def _extract_and_save_lead(lead_match, bot_id, custom_fields_json=""):
    """Extract lead data from AI response and save to DB."""
    from routes.embed.api import sanitize_custom_data

    extracted_content = lead_match.group(1)
    parts = [p.strip() for p in extracted_content.split('|')]

    name = parts[0] if len(parts) > 0 else "Unknown"
    email = parts[1] if len(parts) > 1 else "Unknown"
    phone = parts[2] if len(parts) > 2 else ""
    custom_raw = parts[3] if len(parts) > 3 else "{}"

    custom_data = {}
    try:
        custom_data = json.loads(custom_raw)
    except Exception:
        custom_data = {"Extracted Data": custom_raw}

    custom_data = sanitize_custom_data(custom_data, custom_fields_json)

    existing_lead = Lead.query.filter_by(bot_id=bot_id, email=email).first()

    if existing_lead:
        existing_lead.name = name
        existing_lead.phone = phone
        merged = existing_lead.custom_data or {}
        merged.update(custom_data)
        existing_lead.custom_data = merged
        db.session.commit()
        return existing_lead.id
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
        return new_lead.id


def _build_lead_capture_prompt(ai_prompt, timing, custom_fields):
    """Build lead capture instructions for the AI prompt (mirrors api.py logic)."""
    if not timing or timing == 'disabled' or timing == 'gatekeeper':
        return ai_prompt

    ai_prompt += "\n\n--- LEAD CAPTURE INSTRUCTIONS ---\n"

    custom_field_names = []
    formatting_rules = ""

    if custom_fields:
        try:
            fields_list = json.loads(custom_fields) if isinstance(custom_fields, str) else custom_fields
            for f in fields_list:
                name = f.get('name')
                f_type = f.get('type', 'text')
                if name:
                    custom_field_names.append(name)
                    if f_type == 'number':
                        formatting_rules += (
                            f"  * {name} (STRICT NUMERIC): Raw digits ONLY. "
                            f"Convert '1 crore' to 10000000. If unknown, use 0.\n"
                        )
                    elif f_type == 'email':
                        formatting_rules += f"  * {name}: MUST be a standard email address.\n"
        except Exception:
            pass

    custom_text_str = ", ".join(custom_field_names)
    custom_text = f", and these extra details: {custom_text_str}" if custom_text_str else ""

    if timing.startswith('conv_'):
        ai_prompt += f"Your goal is to collect the user's Name, Email, Phone Number{custom_text} conversationally.\n"

        if 'start' in timing:
            ai_prompt += f"Before answering their very first question, politely ask for their details.\n"
        elif 'middle' in timing:
            ai_prompt += f"After answering 1 or 2 questions, smoothly ask for their details.\n"
        elif 'end' in timing:
            ai_prompt += f"When concluding the chat, politely ask for their details.\n"

        ai_prompt += "\n### DATA INTEGRITY RULES:\n"
        ai_prompt += "1. Reject fake data ('asdf', 'test@test.com', '1234567890').\n"
        if formatting_rules:
            ai_prompt += f"2. FORMATTING:\n{formatting_rules}"

        ai_prompt += (
            "FINAL: Output the tag ONLY ONCE: [[LEAD: Name | Email | Phone | JSON_Custom_Data]]\n"
            "JSON_Custom_Data must include 'Priority' key ('High'/'Medium'/'Low').\n"
            "DO NOT acknowledge this tag in conversation. Append it secretly.\n"
        )

    elif timing.startswith('form_'):
        ai_prompt += "Trigger a visual lead capture form.\n"
        if 'start' in timing:
            ai_prompt += "On your VERY FIRST reply, output [SHOW_FORM].\n"
        elif 'middle' in timing:
            ai_prompt += "After 1-2 answers, output [SHOW_FORM].\n"
        elif 'end' in timing:
            ai_prompt += "When concluding, output [SHOW_FORM].\n"
        ai_prompt += "Include [SHOW_FORM] in your response and the system shows the form.\n"

    return ai_prompt
