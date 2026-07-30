"""Super Admin — Overview / Dashboard page."""
from flask import render_template, request, current_app
from datetime import datetime, timedelta, timezone
from models.models import db, User, Bot, Document, Lead, ScrapeJob, Organization, Payment, Feedback, ChatMessage
from sqlalchemy import func, cast, Date
from . import super_admin_bp
from .decorators import super_admin_required

try:
    import psutil
except ImportError:
    psutil = None


@super_admin_bp.route('/')
@super_admin_required
def dashboard():
    """Main super admin dashboard with comprehensive overview stats."""
    period = request.args.get('period', 'week')
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    # --- Date range ---
    is_custom = False
    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            end_date = datetime.strptime(end_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
            period = 'custom'
            is_custom = True
        except Exception:
            start_date, end_date = now - timedelta(days=7), now
    else:
        end_date = now
        # 'week' = Monday of the current calendar week (not rolling 7 days)
        monday = now - timedelta(days=now.weekday())
        monday_start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
        periods = {
            'today': today_start,
            'week': monday_start,
            'month': now - timedelta(days=30),
            'quarter': now - timedelta(days=90),
            'year': now - timedelta(days=365),
            'all': datetime(2025, 1, 1, tzinfo=timezone.utc),
        }
        start_date = periods.get(period, monday_start)

    days_count = max((end_date - start_date).days, 1)

    # --- Core metrics ---
    # Exclude internal platform org from user/bot counts
    platform_org = Organization.query.filter_by(name='Bubbl Platform').first()
    platform_org_id = platform_org.id if platform_org else -1
    total_users = User.query.filter(User.org_id != platform_org_id).count()
    total_bots = Bot.query.filter(Bot.bot_type != 'platform').count()
    total_docs = Document.query.join(Bot).filter(Bot.bot_type != 'platform').count()
    total_leads = Lead.query.filter(Lead.captured_at >= start_date, Lead.captured_at <= end_date).count()
    total_leads_all = Lead.query.count()
    leads_today = Lead.query.filter(Lead.captured_at >= today_start).count()
    leads_yesterday = Lead.query.filter(Lead.captured_at >= yesterday_start, Lead.captured_at < today_start).count()
    total_conversations = db.session.query(func.count(func.distinct(ChatMessage.session_id))).filter(
        ChatMessage.created_at >= start_date,
        ChatMessage.created_at <= end_date
    ).scalar() or 0
    total_conversations_all = db.session.query(func.count(func.distinct(ChatMessage.session_id))).scalar() or 0
    total_messages = ChatMessage.query.count()
    messages_today = ChatMessage.query.filter(ChatMessage.created_at >= today_start).count()
    messages_yesterday = ChatMessage.query.filter(ChatMessage.created_at >= yesterday_start, ChatMessage.created_at < today_start).count()

    # Users registered in period (exclude platform org)
    new_users_period = User.query.filter(User.created_at >= start_date, User.created_at <= end_date, User.org_id != platform_org_id).count()
    new_users_today = User.query.filter(User.created_at >= today_start, User.org_id != platform_org_id).count()

    # --- Revenue metrics ---
    # Exclude the internal "Bubbl Platform" org from all revenue/plan metrics
    all_orgs = Organization.query.filter(Organization.name != 'Bubbl Platform').all()
    plan_price = current_app.config.get('PLAN_PRICE_INR', {'free': 0, 'starter': 499, 'growth': 1499, 'pro': 4999})

    plan_counts = {'free': 0, 'starter': 0, 'growth': 0, 'pro': 0}
    for o in all_orgs:
        p = (o.plan or 'free')
        plan_counts[p] = plan_counts.get(p, 0) + 1

    active_subscriptions = sum(c for p, c in plan_counts.items() if p != 'free')
    mrr = sum(plan_counts.get(p, 0) * price for p, price in plan_price.items())
    arr = mrr * 12
    total_orgs = len(all_orgs)
    conversion_rate = round((active_subscriptions / total_orgs) * 100, 1) if total_orgs else 0

    # Revenue: today / yesterday / this month / gross
    revenue_today = db.session.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.status == 'completed', Payment.created_at >= today_start
    ).scalar() or 0

    revenue_yesterday = db.session.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.status == 'completed', Payment.created_at >= yesterday_start, Payment.created_at < today_start
    ).scalar() or 0

    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    revenue_this_month = db.session.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.status == 'completed', Payment.created_at >= month_start
    ).scalar() or 0

    revenue_gross = db.session.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.status == 'completed'
    ).scalar() or 0

    total_refunds = db.session.query(func.coalesce(func.sum(Payment.refund_amount), 0)).filter(
        Payment.refund_amount > 0
    ).scalar() or 0

    net_revenue = revenue_gross - total_refunds

    # ═══════════════════════════════════════════
    # API / PERFORMANCE METRICS
    # ═══════════════════════════════════════════
    try:
        all_bots_list = Bot.query.all()
        total_tokens = sum(b.tokens_used or 0 for b in all_bots_list)
        total_interactions = sum(b.interaction_count or 0 for b in all_bots_list)
        total_time = sum(b.total_latency or 0.0 for b in all_bots_list)
        avg_latency_ms = int((total_time / total_interactions) * 1000) if total_interactions > 0 else 0
        avg_tokens_per_msg = int(total_tokens / total_interactions) if total_interactions > 0 else 0
    except Exception:
        total_tokens = total_interactions = avg_latency_ms = avg_tokens_per_msg = 0

    # ═══════════════════════════════════════════
    # SYSTEM HEALTH
    # ═══════════════════════════════════════════
    system_health = {"cpu": "N/A", "memory_used": "N/A", "memory_total": "N/A", "memory_percent": 0, "disk_percent": 0}
    if psutil:
        try:
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            system_health = {
                "cpu": f"{cpu}%",
                "cpu_val": cpu,
                "memory_used": f"{mem.used // (1024**2)}MB",
                "memory_total": f"{mem.total // (1024**2)}MB",
                "memory_percent": mem.percent,
                "disk_percent": disk.percent,
                "disk_used": f"{disk.used // (1024**3)}GB",
                "disk_total": f"{disk.total // (1024**3)}GB",
            }
        except Exception:
            pass

    # ═══════════════════════════════════════════
    # CHART DATA — Leads + Messages over time
    # ═══════════════════════════════════════════
    chart_leads = Lead.query.filter(Lead.captured_at >= start_date, Lead.captured_at <= end_date).all()
    chart_messages = ChatMessage.query.filter(ChatMessage.created_at >= start_date, ChatMessage.created_at <= end_date).all()

    date_counts_leads = {}
    date_counts_msgs = {}
    date_counts_convos = {}

    if days_count <= 2:
        temp = start_date
        while temp <= end_date:
            key = temp.strftime('%H:00')
            date_counts_leads[key] = 0
            date_counts_msgs[key] = 0
            date_counts_convos[key] = 0
            temp += timedelta(hours=1)
        for lead in chart_leads:
            h = lead.captured_at.strftime('%H:00')
            if h in date_counts_leads:
                date_counts_leads[h] += 1
        for msg in chart_messages:
            h = msg.created_at.strftime('%H:00')
            if h in date_counts_msgs:
                date_counts_msgs[h] += 1
        # Conversations: count distinct session_ids per bucket
        chart_convos_raw = ChatMessage.query.filter(
            ChatMessage.created_at >= start_date,
            ChatMessage.created_at <= end_date
        ).with_entities(ChatMessage.session_id, ChatMessage.created_at).all()
        seen_sessions_by_bucket = {}
        for row in chart_convos_raw:
            h = row.created_at.strftime('%H:00')
            if h in date_counts_convos:
                if h not in seen_sessions_by_bucket:
                    seen_sessions_by_bucket[h] = set()
                seen_sessions_by_bucket[h].add(row.session_id)
        for h, sessions in seen_sessions_by_bucket.items():
            date_counts_convos[h] = len(sessions)
    else:
        for i in range(days_count - 1, -1, -1):
            d = (end_date - timedelta(days=i)).strftime('%b %d')
            date_counts_leads[d] = 0
            date_counts_msgs[d] = 0
            date_counts_convos[d] = 0
        for lead in chart_leads:
            d = lead.captured_at.strftime('%b %d')
            if d in date_counts_leads:
                date_counts_leads[d] += 1
        for msg in chart_messages:
            d = msg.created_at.strftime('%b %d')
            if d in date_counts_msgs:
                date_counts_msgs[d] += 1
        # Conversations: count distinct session_ids per day
        chart_convos_raw = ChatMessage.query.filter(
            ChatMessage.created_at >= start_date,
            ChatMessage.created_at <= end_date
        ).with_entities(ChatMessage.session_id, ChatMessage.created_at).all()
        seen_sessions_by_day = {}
        for row in chart_convos_raw:
            d = row.created_at.strftime('%b %d')
            if d in date_counts_convos:
                if d not in seen_sessions_by_day:
                    seen_sessions_by_day[d] = set()
                seen_sessions_by_day[d].add(row.session_id)
        for d, sessions in seen_sessions_by_day.items():
            date_counts_convos[d] = len(sessions)

    chart_data = {
        "labels": list(date_counts_leads.keys()),
        "leads": list(date_counts_leads.values()),
        "messages": list(date_counts_msgs.values()),
        "conversations": list(date_counts_convos.values()),
    }

    # ═══════════════════════════════════════════
    # RECENT ACTIVITY
    # ═══════════════════════════════════════════
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    recent_leads = Lead.query.order_by(Lead.captured_at.desc()).limit(5).all()
    recent_payments = Payment.query.filter_by(status='completed').order_by(Payment.created_at.desc()).limit(5).all()

    # ═══════════════════════════════════════════
    # SCRAPE HEALTH
    # ═══════════════════════════════════════════
    scrapes_pending = ScrapeJob.query.filter_by(status='pending').count()
    scrapes_failed = ScrapeJob.query.filter_by(status='failed').count()
    scrapes_completed = ScrapeJob.query.filter_by(status='completed').count()

    return render_template('super_admin/overview.html',
        # Core
        total_users=total_users, total_bots=total_bots, total_docs=total_docs,
        total_leads=total_leads, total_leads_all=total_leads_all,
        leads_today=leads_today, leads_yesterday=leads_yesterday,
        total_conversations=total_conversations, total_messages=total_messages,
        total_conversations_all=total_conversations_all,
        messages_today=messages_today, messages_yesterday=messages_yesterday,
        new_users_period=new_users_period, new_users_today=new_users_today,
        # Revenue
        active_subscriptions=active_subscriptions, mrr=mrr, arr=arr,
        conversion_rate=conversion_rate, plan_counts=plan_counts, total_orgs=total_orgs,
        revenue_today=revenue_today, revenue_yesterday=revenue_yesterday,
        revenue_this_month=revenue_this_month, revenue_gross=revenue_gross,
        total_refunds=total_refunds, net_revenue=net_revenue,
        # API
        total_tokens=total_tokens, total_interactions=total_interactions,
        avg_latency_ms=avg_latency_ms, avg_tokens_per_msg=avg_tokens_per_msg,
        # System
        system_health=system_health,
        # Charts
        chart_data=chart_data,
        # Recent
        recent_users=recent_users, recent_leads=recent_leads, recent_payments=recent_payments,
        # Scrapes
        scrapes_pending=scrapes_pending, scrapes_failed=scrapes_failed, scrapes_completed=scrapes_completed,
        # Filters
        current_period=period, start_date=start_date.strftime('%Y-%m-%d'),
        end_date=end_date.strftime('%Y-%m-%d'), days_count=days_count, is_custom=is_custom,
    )
