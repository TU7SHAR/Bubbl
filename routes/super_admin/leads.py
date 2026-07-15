"""Super Admin — Leads viewer."""
from flask import render_template, request
from models.models import Lead, Bot, Feedback
from . import super_admin_bp
from .decorators import super_admin_required


@super_admin_bp.route('/leads')
@super_admin_required
def leads_page():
    """Recent leads with search/filter."""
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

    # Feedback stats
    all_feedback = Feedback.query.all()
    avg_rating = 0
    if all_feedback:
        valid = [f.rating for f in all_feedback if f.rating]
        avg_rating = round(sum(valid) / len(valid), 1) if valid else 0

    return render_template('super_admin/leads.html',
        leads=enriched, search=search,
        page=page, total_pages=paginated.pages, total_leads=paginated.total,
        avg_rating=avg_rating, total_feedback=len(all_feedback),
    )
