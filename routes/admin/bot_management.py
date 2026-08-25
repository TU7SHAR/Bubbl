import os
import uuid
import json
import logging
import base64
from flask import request, redirect, url_for, flash, session, render_template, jsonify, current_app
from werkzeug.utils import secure_filename 

from models.models import db, Bot, Document, BotUI, ScrapeJob, Organization
from bot.cloud import upload_to_gemini, delete_from_gemini, create_dynamic_store
from routes.auth.decorators import admin_required
from extensions import cache
from . import admin_bp
from tasks.scrape_tasks import async_scrape_task
from utils.plan_limits import check_bot_limit
from utils.lead_fields import normalize_custom_fields, rejection_message


def invalidate_bot_cache(bot_id):
    """Clear cached config + avatar for a bot after it's edited or deleted."""
    cache.delete(f"bot_config_{bot_id}")
    cache.delete(f"bot_avatar_{bot_id}")

@admin_bp.route('/create_pipeline', methods=['GET', 'POST'])
def create_pipeline():
    if request.method == 'GET':
        return render_template('create_pipeline.html')

    # --- BOT LIMIT CHECK ---
    allowed, current, limit = check_bot_limit(session.get('org_id'))
    if not allowed:
        return jsonify({"success": False, "error": f"Bot limit reached ({current}/{limit}). Please upgrade your plan."}), 403

    bot_name = request.form.get('bot_name')
    bot_type = request.form.get('bot_type')
    visibility = request.form.get('visibility')
    system_prompt = request.form.get('system_prompt')
    
    glass_opacity = request.form.get('glass_opacity', 35, type=int)
    glass_blur = request.form.get('glass_blur', 25, type=int)
    
    theme_color = request.form.get('theme_color', '#E8722A')
    lead_capture_timing = request.form.get('lead_capture_timing', 'disabled')
    header_color = request.form.get('header_color', '#FFFFFF')
    theme_mode = request.form.get('theme_mode', 'light')
    # Drops names that collide with the built-in name/email/phone inputs,
    # trims, and dedupes. See utils/lead_fields.py.
    custom_form_fields, rejected_fields = normalize_custom_fields(
        request.form.get('custom_form_fields', '[]')
    )
    rejection = rejection_message(rejected_fields)
    if rejection:
        flash(rejection, "error")
    
    store_id = create_dynamic_store(bot_name)
    if not store_id:
        store_id = str(uuid.uuid4())

    access_key = None
    if visibility == 'private':
        access_key = uuid.uuid4().hex[:4].upper()

    new_bot = Bot(
        bot_name=bot_name,
        bot_type=bot_type,
        visibility=visibility,
        system_prompt=system_prompt,
        created_by=session.get('user_id'),
        org_id=session.get('org_id'), 
        store_id=store_id,
        access_key=access_key,
        lead_capture_timing=lead_capture_timing,
        custom_form_fields=custom_form_fields
        
    )
    db.session.add(new_bot)
    db.session.flush()

    avatar_file = request.files.get('bot_avatar')
    avatar_base64_str = None
    
    if avatar_file and avatar_file.filename != '':
        img_bytes = avatar_file.read()
        b64_encoded = base64.b64encode(img_bytes).decode('utf-8')
        avatar_base64_str = f"data:{avatar_file.mimetype};base64,{b64_encoded}"

    new_ui = BotUI(
        bot_id=new_bot.id,
        theme_color=theme_color,
        header_color=header_color,
        theme_mode=theme_mode,
        avatar_base64=avatar_base64_str,
        glass_opacity=glass_opacity, 
        glass_blur=glass_blur
    )
    db.session.add(new_ui)
    
    pipeline_logs = []

    uploaded_files = request.files.getlist('file')
    for uploaded_file in uploaded_files:
        if uploaded_file and uploaded_file.filename != '':
            safe_name = secure_filename(uploaded_file.filename)
            filename = f"{uuid.uuid4().hex}_{safe_name}"
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            
            uploaded_file.save(filepath)

            new_doc = Document(bot_id=new_bot.id, filename=filename)
            db.session.add(new_doc)
            
            try:
                upload_to_gemini(filepath, new_bot.store_id)
                pipeline_logs.append(f"[File] Vectorized successfully: {safe_name}")
            except Exception as e:
                pipeline_logs.append(f"[Error] Gemini Upload Error for {safe_name}: {e}")

    text_snippets_data = request.form.get('text_snippets_data')
    if text_snippets_data:
        snippets = json.loads(text_snippets_data)
        for snippet in snippets:
            title = snippet.get('title', 'Untitled')
            content = snippet.get('text', '')
            if content.strip():
                safe_title = "".join(x for x in title if x.isalnum() or x in " _-").strip()
                if not safe_title:
                    safe_title = "TextSnippet"
                
                txt_filename = f"{safe_title}_{uuid.uuid4().hex[:6]}.txt"
                txt_filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], txt_filename)
                
                with open(txt_filepath, 'w', encoding='utf-8') as f:
                    f.write(f"Title: {title}\n\n{content}")

                new_doc = Document(bot_id=new_bot.id, filename=txt_filename)
                db.session.add(new_doc)
                
                try:
                    upload_to_gemini(txt_filepath, new_bot.store_id)
                    pipeline_logs.append(f"[Text] Vectorized snippet: {safe_title}")
                except Exception as e:
                    pipeline_logs.append(f"[Error] Gemini Text Upload Error for {title}: {e}")

    qa_text = request.form.get('qa_text')
    if qa_text and qa_text.strip():
        qa_filename = f"qa_knowledge_{uuid.uuid4().hex[:6]}.txt"
        qa_filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], qa_filename)
        
        with open(qa_filepath, 'w', encoding='utf-8') as f:
            f.write("Q&A Knowledge Base:\n\n" + qa_text)

        new_doc_qa = Document(bot_id=new_bot.id, filename=qa_filename)
        db.session.add(new_doc_qa)
        
        try:
            upload_to_gemini(qa_filepath, new_bot.store_id)
            pipeline_logs.append("[Q&A] Vectorized custom Q&A pairs")
        except Exception as e:
            pipeline_logs.append(f"[Error] Gemini Q&A Upload Error: {e}")

    scrape_url = request.form.get('scrape_url')
    if scrape_url and scrape_url.strip():
        url_to_scrape = scrape_url.strip()
        use_spider = request.form.get('use_deep_crawl') == 'on' 
        max_urls = int(request.form.get('max_urls', 20))

        new_job = ScrapeJob(bot_id=new_bot.id, url=url_to_scrape, status='pending', limit=max_urls)
        db.session.add(new_job)
        db.session.flush() 

        # Queue scrape in Celery (runs in separate worker process)
        async_scrape_task.delay(new_job.id, url_to_scrape, new_bot.id, use_spider)

    db.session.commit()    
    
    session['active_bot_id'] = new_bot.id
    session['active_bot_name'] = new_bot.bot_name
    session['lead_capture_timing'] = new_bot.lead_capture_timing
    session['theme_color'] = new_ui.theme_color
    session['header_color'] = new_ui.header_color
    session['theme_mode'] = new_ui.theme_mode
    session['glass_opacity'] = new_ui.glass_opacity
    session['glass_blur'] = new_ui.glass_blur
    session['custom_form_fields'] = json.dumps(new_bot.custom_form_fields) if isinstance(new_bot.custom_form_fields, list) else (new_bot.custom_form_fields or '[]')

    return jsonify({"success": True, "bot_id": new_bot.id, "logs": pipeline_logs})

@admin_bp.route('/rename_bot/<int:bot_id>', methods=['POST'])
def rename_bot(bot_id):
    try:
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))

        new_name = request.form.get('new_bot_name')
        if not new_name or new_name.strip() == '':
            flash("Error: Bot name cannot be empty.", "error")
            return redirect(url_for('admin_bp.admin_dashboard'))

        target_bot = Bot.query.filter_by(id=bot_id, org_id=session['org_id']).first()
        if target_bot:
            target_bot.bot_name = new_name.strip()
            db.session.commit()
            invalidate_bot_cache(bot_id)

            if session.get('active_bot_id') == bot_id:
                session['active_bot_name'] = target_bot.bot_name

            flash(f"Bot renamed to '{target_bot.bot_name}'", "success")
        else:
            flash("Security Error: Bot not found.", "error")

        return redirect(request.referrer or url_for('views_bp.admin_dashboard'))
    except Exception as e:
        logging.error(f"[rename_bot] Unhandled error: {e}", exc_info=True)
        db.session.rollback()
        flash("Something went wrong. Please try again.", "error")
        return redirect(url_for('views_bp.dashboard'))

@admin_bp.route('/edit_bot/<int:bot_id>', methods=['GET'])
@admin_required
def edit_bot(bot_id):
    try:
        target_bot = Bot.query.filter_by(id=bot_id, org_id=session['org_id']).first()
        # Also allow editing the platform bot (belongs to a different org but accessible to all logged-in users)
        if not target_bot:
            target_bot = Bot.query.filter_by(id=bot_id, bot_type='platform').first()
        if not target_bot:
            flash("Bot not found.", "error")
            return redirect(url_for('views_bp.dashboard'))
        ingested_docs = Document.query.filter_by(bot_id=bot_id).all()
    
        # Pass org plan message limit for the "leave empty to use plan limit" hint
        from utils.plan_limits import PLAN_LIMITS
        org = Organization.query.get(session.get('org_id'))
        plan_name = (org.plan if org else 'free') or 'free'
        messages_limit = PLAN_LIMITS.get(plan_name, PLAN_LIMITS['free']).get('messages', 200)
    
        return render_template('edit_bot.html', bot=target_bot, docs=ingested_docs, messages_limit=messages_limit)
    except Exception as e:
        logging.error(f"[edit_bot] Unhandled error: {e}", exc_info=True)
        db.session.rollback()
        flash("Something went wrong. Please try again.", "error")
        return redirect(url_for('views_bp.dashboard'))

@admin_bp.route('/delete_bot/<int:bot_id>', methods=['POST'])
def delete_bot(bot_id):
    try:
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))

        target_bot = Bot.query.filter_by(id=bot_id, org_id=session['org_id']).first()
        if target_bot:
            docs = Document.query.filter_by(bot_id=target_bot.id).all()
            for doc in docs:
                delete_from_gemini(doc.filename, store_id=target_bot.store_id)

            db.session.delete(target_bot)
            db.session.commit()
            invalidate_bot_cache(bot_id)
       
            fallback = Bot.query.filter_by(org_id=session.get('org_id')).first()
            if fallback:
                session['active_bot_id'] = fallback.id
                session['active_bot_name'] = fallback.bot_name
            
                if fallback.ui_settings:
                    session['theme_color'] = fallback.ui_settings.theme_color
                    session['header_color'] = fallback.ui_settings.header_color
                    session['theme_mode'] = fallback.ui_settings.theme_mode
            else:
                session.pop('active_bot_id', None)
                session.pop('active_bot_name', None)
                session.pop('theme_color', None)
                session.pop('header_color', None)
                session.pop('theme_mode', None)

            flash(f"Bot: '{target_bot.bot_name}' permanently deleted.", "success")
        else:
            flash("Security Error: Bot not found.", "error")

        return redirect(request.referrer or url_for('admin_bp.admin_dashboard'))
    except Exception as e:
        logging.error(f"[delete_bot] Unhandled error: {e}", exc_info=True)
        db.session.rollback()
        flash("Something went wrong. Please try again.", "error")
        return redirect(url_for('views_bp.dashboard'))

@admin_bp.route('/update_bot/<int:bot_id>', methods=['POST'])
def update_bot(bot_id):
    try:
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))

        bot = Bot.query.filter_by(id=bot_id, org_id=session['org_id']).first()
        if not bot:
            bot = Bot.query.filter_by(id=bot_id, bot_type='platform').first()
        if not bot:
            flash("Error: Bot not found.", "error")
            return redirect(url_for('views_bp.dashboard'))

        bot.bot_name = request.form.get('bot_name', bot.bot_name)
        bot.bot_type = request.form.get('bot_type', bot.bot_type)
        bot.visibility = request.form.get('visibility', bot.visibility)
        bot.system_prompt = request.form.get('system_prompt', bot.system_prompt)
        bot.access_key = request.form.get('access_key', bot.access_key)
        bot.lead_capture_timing = request.form.get('lead_capture_timing', bot.lead_capture_timing)
        # Only touch the field list when the form actually submitted one, so a
        # post that does not include the Lead Conventions tab leaves it alone.
        # normalize_custom_fields drops reserved/duplicate names and, if the
        # value is unparseable, returns the current list rather than wiping it.
        submitted_fields = request.form.get('custom_form_fields')
        if submitted_fields is not None:
            bot.custom_form_fields, rejected_fields = normalize_custom_fields(
                submitted_fields, fallback=bot.custom_form_fields
            )
            rejection = rejection_message(rejected_fields)
            if rejection:
                flash(rejection, "error")

        # Per-bot message limit (empty = use org plan limit)
        msg_limit_raw = request.form.get('message_limit', '').strip()
        bot.message_limit = int(msg_limit_raw) if msg_limit_raw else None

        if not bot.ui_settings:
            bot.ui_settings = BotUI(bot_id=bot.id)

        bot.ui_settings.theme_color = request.form.get('theme_color', bot.ui_settings.theme_color)
        bot.ui_settings.header_color = request.form.get('header_color', bot.ui_settings.header_color)
        bot.ui_settings.theme_mode = request.form.get('theme_mode', bot.ui_settings.theme_mode)
    
        bot.ui_settings.glass_opacity = request.form.get('glass_opacity', bot.ui_settings.glass_opacity, type=int)
        bot.ui_settings.glass_blur = request.form.get('glass_blur', bot.ui_settings.glass_blur, type=int)

        # --- EXTENDED UI CUSTOMIZATION ---
        # Text fields: store None when blank so the widget falls back to defaults
        def _opt(field):
            val = (request.form.get(field) or '').strip()
            return val if val else None

        if 'greeting_message' in request.form:
            bot.ui_settings.greeting_message = _opt('greeting_message')
        if 'input_placeholder' in request.form:
            bot.ui_settings.input_placeholder = _opt('input_placeholder')
        if 'header_title' in request.form:
            bot.ui_settings.header_title = _opt('header_title')
        if 'user_bubble_color' in request.form:
            bot.ui_settings.user_bubble_color = _opt('user_bubble_color')
        if 'bot_bubble_color' in request.form:
            bot.ui_settings.bot_bubble_color = _opt('bot_bubble_color')
        if 'font_family' in request.form:
            bot.ui_settings.font_family = request.form.get('font_family') or 'Inter'
        if 'widget_position' in request.form:
            bot.ui_settings.widget_position = request.form.get('widget_position') or 'bottom-right'
        if 'bubble_radius' in request.form:
            bot.ui_settings.bubble_radius = request.form.get('bubble_radius', 16, type=int)
        if 'font_size' in request.form:
            bot.ui_settings.font_size = request.form.get('font_size', 14, type=int)
        # Checkbox: only present in POST when checked
        if request.form.get('_ui_form') or 'font_family' in request.form:
            bot.ui_settings.show_branding = bool(request.form.get('show_branding'))

        avatar_file = request.files.get('bot_avatar')
        if avatar_file and avatar_file.filename != '':
            img_bytes = avatar_file.read()
            b64_encoded = base64.b64encode(img_bytes).decode('utf-8')
            bot.ui_settings.avatar_base64 = f"data:{avatar_file.mimetype};base64,{b64_encoded}"

        db.session.commit()
        invalidate_bot_cache(bot_id)
    
        if session.get('active_bot_id') == bot.id:
            session['active_bot_name'] = bot.bot_name
            session['lead_capture_timing'] = bot.lead_capture_timing
            session['theme_color'] = bot.ui_settings.theme_color
            session['header_color'] = bot.ui_settings.header_color
            session['theme_mode'] = bot.ui_settings.theme_mode
            session['glass_opacity'] = bot.ui_settings.glass_opacity
            session['glass_blur'] = bot.ui_settings.glass_blur
            session['custom_form_fields'] = json.dumps(bot.custom_form_fields) if isinstance(bot.custom_form_fields, list) else (bot.custom_form_fields or '[]')

        flash("Bot configurations updated successfully!", "success")
        return redirect(url_for('admin_bp.edit_bot', bot_id=bot.id))
    except Exception as e:
        logging.error(f"[update_bot] Unhandled error: {e}", exc_info=True)
        db.session.rollback()
        flash("Something went wrong. Please try again.", "error")
        return redirect(url_for('views_bp.dashboard'))

@admin_bp.route('/add_knowledge/<int:bot_id>', methods=['POST'])
def add_knowledge(bot_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    bot = Bot.query.filter_by(id=bot_id, org_id=session['org_id']).first()
    if not bot:
        bot = Bot.query.filter_by(id=bot_id, bot_type='platform').first()
    if not bot:
        flash("Error: Bot not found.", "error")
        return redirect(url_for('views_bp.dashboard'))

    file = request.files.get('file')
    if file and file.filename != '':
        filename = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        new_doc = Document(bot_id=bot.id, filename=filename)
        db.session.add(new_doc)
        db.session.commit()

        try:
            upload_to_gemini(filepath, bot.store_id)
            flash(f"Success: '{file.filename}' added to knowledge base.", "success")
        except Exception as e:
            flash(f"Gemini Upload Error: {str(e)}", "error")
    else:
        flash("Error: No file selected.", "error")

    return redirect(url_for('admin_bp.edit_bot', bot_id=bot.id))

@admin_bp.route('/delete_doc/<int:doc_id>', methods=['GET', 'POST'])
def delete_doc(doc_id):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    doc = Document.query.get_or_404(doc_id)
    
    bot = Bot.query.filter_by(id=doc.bot_id, org_id=session['org_id']).first()
    # Also allow deleting docs from the platform bot (different org, but manageable by admins)
    if not bot:
        bot = Bot.query.filter_by(id=doc.bot_id, bot_type='platform').first()
    if bot:
        try:
            delete_from_gemini(doc.filename, store_id=bot.store_id)
        except Exception as e:
            logging.error(f"Gemini Delete Error: {e}")
            
        db.session.delete(doc)
        db.session.commit()
        flash("Document deleted from Vector Store.", "success")
    else:
        flash("Security Error: Unauthorized to delete this document.", "error")

    return redirect(url_for('admin_bp.edit_bot', bot_id=bot.id))



# ═══════════════════════════════════════════
# MANAGED LINKS — Clickable buttons for chat responses
# ═══════════════════════════════════════════

@admin_bp.route('/bot/<int:bot_id>/links', methods=['GET'])
def get_bot_links(bot_id):
    """Get managed links for a bot."""
    try:
        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401

        bot = Bot.query.filter_by(id=bot_id, org_id=session['org_id']).first()
        if not bot:
            bot = Bot.query.filter_by(id=bot_id, bot_type='platform').first()
        if not bot:
            return jsonify({"error": "Bot not found"}), 404

        links = bot.managed_links or []
        return jsonify({"success": True, "links": links})
    except Exception as e:
        logging.error(f"[get_bot_links] Unhandled error: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "An internal error occurred. Please try again."}), 500


@admin_bp.route('/api/bot_link_colors/<int:bot_id>', methods=['GET'])
def get_bot_link_colors(bot_id):
    """
    Public endpoint — returns managed link colors for a bot (used by the chat widget).
    Maps URL → color so renderButtons can apply custom colors without relying on the AI.
    """
    try:
        bot = Bot.query.get(bot_id)
        if not bot:
            return jsonify({}), 404

        links = bot.managed_links or []
        # Build a URL → {color, category} map
        color_map = {}
        for link in links:
            url = link.get('url', '').strip()
            color = link.get('color', '')
            category = link.get('category', 'link')
            if url:
                color_map[url] = {"color": color, "category": category}

        return jsonify(color_map)
    except Exception as e:
        logging.error(f"[get_bot_link_colors] Unhandled error: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "An internal error occurred. Please try again."}), 500


@admin_bp.route('/bot/<int:bot_id>/links', methods=['POST'])
def save_bot_links(bot_id):
    """Save managed links for a bot (replaces all)."""
    try:
        if 'user_id' not in session:
            return jsonify({"error": "Unauthorized"}), 401

        bot = Bot.query.filter_by(id=bot_id, org_id=session['org_id']).first()
        if not bot:
            bot = Bot.query.filter_by(id=bot_id, bot_type='platform').first()
        if not bot:
            return jsonify({"error": "Bot not found"}), 404

        data = request.get_json(silent=True) or {}
        links = data.get('links', [])

        valid_categories = ['pricing', 'action', 'info', 'support', 'link', 'email', 'phone']
        import re as _re
        cleaned = []
        for link in links:
            label = (link.get('label') or '').strip()
            url = (link.get('url') or '').strip()
            category = (link.get('category') or 'link').strip().lower()
            color = (link.get('color') or '').strip()
            if label and url:
                if category not in valid_categories:
                    category = 'link'
                entry = {"label": label, "url": url, "category": category}
                # Store a custom button colour only if it's a valid hex value
                if _re.match(r'^#[0-9a-fA-F]{3,8}$', color):
                    entry["color"] = color
                cleaned.append(entry)

        bot.managed_links = cleaned
        db.session.commit()
        invalidate_bot_cache(bot_id)

        return jsonify({"success": True, "count": len(cleaned)})
    except Exception as e:
        logging.error(f"[save_bot_links] Unhandled error: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({"error": "An internal error occurred. Please try again."}), 500



# ═══════════════════════════════════════════
# CHAT HISTORY
# ═══════════════════════════════════════════
# The bot_chats / bot_chat_detail pair used to live here and was a narrower
# duplicate of views_bp.conversations_list / conversation_detail — same
# aggregation query, same transcript read, fewer features. The "Chat History"
# tab on the Edit Bot page now links to those views with ref=edit.

