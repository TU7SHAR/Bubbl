"""Super Admin — Feedback viewer (separate from Leads)."""
from flask import render_template
from models.models import Feedback, Bot, Lead
from . import super_admin_bp
from .decorators import super_admin_required
import logging


@super_admin_bp.route('/feedback')
@super_admin_required
def feedback_page():
    """All feedback with ratings, comments, bot info."""
    try:
        all_feedback = Feedback.query.order_by(Feedback.created_at.desc()).all()

        enriched = []
        total_rating = 0
        valid_count = 0

        for fb in all_feedback:
            bot = Bot.query.get(fb.bot_id) if fb.bot_id else None
            lead = Lead.query.get(fb.lead_id) if fb.lead_id else None

            enriched.append({
                'id': fb.id,
                'bot_name': bot.bot_name if bot else 'Platform (Bubbl)',
                'lead_name': lead.name if lead else None,
                'lead_email': lead.email if lead else None,
                'rating': fb.rating,
                'comment': fb.comment,
                'created_at': fb.created_at,
            })

            if fb.rating:
                total_rating += fb.rating
                valid_count += 1

        avg_rating = round(total_rating / valid_count, 1) if valid_count > 0 else 0

        return render_template('super_admin/feedback.html',
            feedbacks=enriched, avg_rating=avg_rating, total_feedback=len(all_feedback))
    except Exception as e:
        logging.error(f"[feedback_page] Unhandled error: {e}", exc_info=True)
        db.session.rollback()
        flash("Something went wrong. Please try again.", "error")
        return redirect(url_for('views_bp.dashboard'))

