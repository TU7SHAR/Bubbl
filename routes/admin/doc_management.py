# admin/doc_management.py
import os
from flask import request, redirect, url_for, flash, current_app, session
from werkzeug.utils import secure_filename
from models.models import db, Bot, Document
from bot.cloud import upload_to_gemini, delete_from_gemini
from utils.plan_limits import check_document_limit
from . import admin_bp

def allowed_file(filename):
    allowed = current_app.config.get('ALLOWED_EXTENSIONS', {'txt', 'doc', 'docx', 'pdf'})
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed

@admin_bp.route('/upload', methods=['POST'])
def upload_file():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    if 'file' not in request.files:
        flash('File not in requested Files')
        return redirect(url_for('admin_bp.admin_dashboard'))
    
    file = request.files['file']
    if file.filename == '':
        flash('file name is blank')
        return redirect(url_for('admin_bp.admin_dashboard'))
    
    if file and allowed_file(file.filename):
        file.seek(0, os.SEEK_END) 
        file_size = file.tell()    
        file.seek(0, os.SEEK_SET)  
        
        if file_size > current_app.config.get('MAX_CONTENT_LENGTH', 10*1024*1024): 
            flash('Upload failed: File exceeds maximum limit.')
            return redirect(url_for('admin_bp.admin_dashboard'))
        
        active_bot_id = session.get('active_bot_id')
        if not active_bot_id:
            flash("Error: No active Bot selected.", "error")
            return redirect(url_for('admin_bp.admin_dashboard'))
            
        user_bot = Bot.query.filter_by(id=active_bot_id, org_id=session['org_id']).first()
        
        if not user_bot:
            flash("Error: Active bot not found in database.", "error")
            return redirect(url_for('admin_bp.admin_dashboard'))

        # --- PLAN LIMIT: Check document count ---
        allowed, current_docs, doc_limit = check_document_limit(session['org_id'], user_bot.id)
        if not allowed:
            flash(f"Document limit reached ({current_docs}/{doc_limit}). Please upgrade your plan to add more files.", "error")
            return redirect(url_for('admin_bp.admin_dashboard'))

        filename = secure_filename(file.filename)
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        existing_doc = Document.query.filter_by(bot_id=user_bot.id, filename=filename).first()
        
        if existing_doc:
            delete_from_gemini(filename)
        else:
            new_doc = Document(bot_id=user_bot.id, filename=filename)
            db.session.add(new_doc)
            db.session.commit()

        upload_to_gemini(file_path, user_bot.store_id)
        flash(f"Uploaded File: {filename} to {user_bot.bot_name}")
        
        if os.path.exists(file_path):
            os.remove(file_path)

    else:
        flash('Invalid File Type')

    return redirect(url_for('admin_bp.admin_dashboard'))

@admin_bp.route('/delete/<path:filename>')
def delete_file(filename):
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
        
    active_bot_id = session.get('active_bot_id')
    user_bot = Bot.query.filter_by(id=active_bot_id, org_id=session['org_id']).first()
    search_name = filename or secure_filename(filename)

    if user_bot:
        doc_to_delete = Document.query.filter_by(bot_id=user_bot.id, 
                                                 filename = search_name).first()
        
        if doc_to_delete:
            db.session.delete(doc_to_delete)
            db.session.commit()            
            delete_from_gemini(filename)
            flash(f"File Deleted: {filename} from {user_bot.bot_name}", "success")
        else:
            flash(f"Error: File '{filename}' does not exist in this Bot.", "error")
    else:
        flash("No active bot found.", "error")

    return redirect(url_for('admin_bp.admin_dashboard'))