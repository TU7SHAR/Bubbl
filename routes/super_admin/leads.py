"""Super Admin — Leads viewer."""
import csv
import io

from flask import render_template, request, make_response
from models.models import Lead, Bot
from . import super_admin_bp
from .decorators import super_admin_required
import logging


@super_admin_bp.route('/leads')
@super_admin_required
def leads_page():
    """Recent leads with search/filter."""
    try:
        search = request.args.get('q', '').strip()
        page = request.args.get('page', 1, type=int)
        per_page = 50

        query = Lead.query.order_by(Lead.captured_at.desc())
        if search:
            query = query.filter(
                (Lead.name.ilike(f'%{search}%')) |
                (Lead.email.ilike(f'%{search}%'))
            )

        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        leads = paginated.items

        enriched = []
        for l in leads:
            bot = Bot.query.get(l.bot_id)
            enriched.append({
                'id': l.id,
                'name': l.name,
                'email': l.email,
                'phone': l.phone,
                'bot_name': bot.bot_name if bot else 'Unknown',
                'priority': (l.custom_data or {}).get('Priority', 'Low'),
                'captured_at': l.captured_at,
                'custom_data': l.custom_data,
            })

        # Lead-specific stats
        high_priority_count = sum(1 for l in enriched if l['priority'] == 'High')
        source_bots_count = len(set(l.bot_id for l in leads))

        return render_template('super_admin/leads.html',
            leads=enriched, search=search,
            page=page, total_pages=paginated.pages, total_leads=paginated.total,
            high_priority_count=high_priority_count, source_bots_count=source_bots_count,
        )
    except Exception as e:
        logging.error(f"[leads_page] Unhandled error: {e}", exc_info=True)
        db.session.rollback()
        flash("Something went wrong. Please try again.", "error")
        return redirect(url_for('views_bp.dashboard'))


# ═══════════════════════════════════════════
# NEW ROUTES
# ═══════════════════════════════════════════


@super_admin_bp.route('/leads/export')
@super_admin_required
def export_leads_csv():
    """Export all leads as a CSV download."""
    try:
        all_leads = Lead.query.order_by(Lead.captured_at.desc()).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['name', 'email', 'phone', 'bot_name', 'priority', 'captured_at'])

        for l in all_leads:
            bot = Bot.query.get(l.bot_id)
            bot_name = bot.bot_name if bot else 'Unknown'
            priority = (l.custom_data or {}).get('Priority', 'Low')
            writer.writerow([l.name, l.email, l.phone or '', bot_name, priority, str(l.captured_at or '')])

        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = 'attachment; filename=leads_export.csv'
        return response
    except Exception as e:
        logging.error(f"[export_leads_csv] Unhandled error: {e}", exc_info=True)
        db.session.rollback()
        flash("Something went wrong. Please try again.", "error")
        return redirect(url_for('views_bp.dashboard'))

