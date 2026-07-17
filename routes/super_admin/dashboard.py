"""Super Admin — Overview / Dashboard page."""
from flask import render_template, request
from datetime import datetime, timedelta
from models.models import db, User, Bot, Document, Lead, ScrapeJob, Organization, Payment, Feedback, ChatMessage
from . import super_admin_bp
from .decorators import super_admin_required

try:
    import psutil
except ImportError:
    psutil = None


@super_admin_bp.route('/')
@super_admin_required
def dashboard():
    """Main super admin dashboard with overview stats."""
    period = request.args.get('period', 'week')
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # --- Date range ---
    is_custom = False
    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            period = 'custom'
            is_custom = True
        except Exception:
            start_date, end_date = now - timedelta(days=7), now
    else:
        end_date = now
        periods = {
            'today': today_start,
            'week': now - timedelta(days=7),
            'month': now - timedelta(days=30),
            'quarter': now - timedelta(days=90),
            'year': now - timedelta(days=365),
        }
        start_date = periods.get(period, datetime(2025, 1, 1))

    days_count = max((end_date - start_date).days, 1)

    # --- Core metrics ---
    # Exclude internal platform org from user/bot counts
    platform_org = Organization.query.filter_by(name='Bubbl Platform').first()
    platform_org_id = platform_org.id if platform_org else -1
    total_users = User.query.filter(User.org_id != platform_org_id).count()
    total_bots = Bot.query.filter(Bot.bot_type != 'platform').count()
    total_docs = Document.query.count()
    total_leads = Lead.query.filter(Lead.captured_at >= start_date, Lead.captured_at <= end_date).count()
    total_hits_today = Lead.query.filter(Lead.captured_at >= today_start).count()
    total_conversations = db.session.query(db.func.count(db.func.distinct(ChatMessage.session_id))).scalar() or 0
    total_messages = ChatMessage.query.count()

    # --- Revenue metrics ---
    # Exclude the internal "Bubbl Platform" org from all revenue/plan metrics
    all_orgs = Organization.query.filter(Organization.name != 'Bubbl Platform').all()
    from flask import current_app
    plan_price = current_app.config.get('PLAN_PRICE_INR', {'free': 0, 'starter': 499, 'growth': 1499, 'pro': 4999})

    plan_counts = {'free': 0, 'starter': 0, 'growth': 0, 'pro': 0}
    for o in all_orgs:
        p = (o.plan or 'free')
        plan_counts[p] = plan_counts.get(p, 0) + 1

    active_subscriptions = sum(c for p, c in plan_counts.items() if p != 'free')
    mrr = sum(plan_counts.get(p, 0) * price for p, price in plan_price.items())
    conversion_rate = round((active_subscriptions / len(all_orgs)) * 100, 1) if all_orgs else 0

    # --- Chart data (leads per day/hour) ---
    chart_leads = Lead.query.filter(Lead.captured_at >= start_date, Lead.captured_at <= end_date).all()
    date_counts = {}
    if days_count <= 2:
        temp = start_date
        while temp <= end_date:
            date_counts[temp.strftime('%H:00')] = 0
            temp += timedelta(hours=1)
        for lead in chart_leads:
            h = lead.captured_at.strftime('%H:00')
            if h in date_counts:
                date_counts[h] += 1
    else:
        for i in range(days_count - 1, -1, -1):
            d = (end_date - timedelta(days=i)).strftime('%b %d')
            date_counts[d] = 0
        for lead in chart_leads:
            d = lead.captured_at.strftime('%b %d')
            if d in date_counts:
                date_counts[d] += 1

    chart_data = {"labels": list(date_counts.keys()), "data": list(date_counts.values())}

    # --- System health ---
    system_health = {"cpu": "N/A", "memory": "N/A"}
    if psutil:
        try:
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            system_health = {"cpu": f"{cpu}%", "memory": f"{mem.used // (1024**3)}GB / {mem.total // (1024**3)}GB"}
        except Exception:
            pass

    # --- API metrics (graceful) ---
    try:
        all_bots_list = Bot.query.all()
        total_tokens = sum(b.tokens_used or 0 for b in all_bots_list)
        total_interactions = sum(b.interaction_count or 0 for b in all_bots_list)
        total_time = sum(b.total_latency or 0.0 for b in all_bots_list)
        avg_latency_ms = int((total_time / total_interactions) * 1000) if total_interactions > 0 else 0
    except Exception:
        total_tokens = total_interactions = avg_latency_ms = 0

    return render_template('super_admin/overview.html',
        total_users=total_users, total_bots=total_bots, total_docs=total_docs,
        total_leads=total_leads, total_hits_today=total_hits_today,
        total_conversations=total_conversations, total_messages=total_messages,
        active_subscriptions=active_subscriptions, mrr=mrr, conversion_rate=conversion_rate,
        plan_counts=plan_counts, chart_data=chart_data,
        system_health=system_health,
        total_tokens=total_tokens, total_interactions=total_interactions, avg_latency_ms=avg_latency_ms,
        current_period=period, start_date=start_date.strftime('%Y-%m-%d'),
        end_date=end_date.strftime('%Y-%m-%d'), days_count=days_count, is_custom=is_custom,
    )
