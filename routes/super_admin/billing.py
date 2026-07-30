"""Super Admin — Revenue & Billing."""
from flask import render_template, jsonify, current_app
from sqlalchemy import extract, func
from datetime import datetime, timezone
from models.models import db, Payment, Organization
from . import super_admin_bp
from .decorators import super_admin_required


@super_admin_bp.route('/billing')
@super_admin_required
def billing_page():
    """Revenue metrics and payment history."""
    plan_price = current_app.config.get('PLAN_PRICE_INR', {'free': 0, 'starter': 499, 'growth': 1499, 'pro': 4999})

    all_orgs = Organization.query.filter(Organization.name != 'Bubbl Platform').all()
    plan_counts = {'free': 0, 'starter': 0, 'growth': 0, 'pro': 0}
    for o in all_orgs:
        plan_counts[o.plan or 'free'] = plan_counts.get(o.plan or 'free', 0) + 1

    active_subs = sum(c for p, c in plan_counts.items() if p != 'free')
    mrr = sum(plan_counts.get(p, 0) * price for p, price in plan_price.items())
    arr = mrr * 12

    all_payments = Payment.query.filter_by(status='completed').order_by(Payment.created_at.desc()).all()
    total_revenue = sum(p.amount or 0 for p in all_payments)
    total_tax = sum(getattr(p, 'tax_amount', 0) or 0 for p in all_payments)
    total_revenue_after_tax = total_revenue - total_tax
    total_refunds = sum(p.refund_amount or 0 for p in all_payments if p.refund_amount)
    net_revenue = total_revenue - total_refunds - total_tax

    revenue_by_plan = [
        {'plan': p.capitalize(), 'count': plan_counts.get(p, 0), 'price': plan_price.get(p, 0),
         'mrr': plan_counts.get(p, 0) * plan_price.get(p, 0)}
        for p in ['starter', 'growth', 'pro']
    ]

    recent_payments = []
    for pm in all_payments[:100]:
        recent_payments.append({
            'created_at': pm.created_at,
            'email': pm.customer_email or 'N/A',
            'plan': (pm.plan or 'N/A').capitalize(),
            'amount': pm.amount or 0,
            'transaction_id': pm.paddle_transaction_id or '—',
            'status': pm.status or 'completed',
            'tax': getattr(pm, 'tax_amount', 0) or 0,
        })

    return render_template('super_admin/billing.html',
        mrr=mrr, arr=arr, active_subscriptions=active_subs,
        total_revenue=total_revenue, revenue_by_plan=revenue_by_plan,
        recent_payments=recent_payments, plan_counts=plan_counts,
        total_tax=total_tax,
        total_revenue_after_tax=total_revenue_after_tax,
        total_refunds=total_refunds,
        net_revenue=net_revenue,
    )


# ═══════════════════════════════════════════
# NEW ROUTES
# ═══════════════════════════════════════════


@super_admin_bp.route('/billing/chart')
@super_admin_required
def billing_chart():
    """Return monthly revenue data for the last 12 months as JSON."""
    now = datetime.now(timezone.utc)

    # Query payments grouped by year-month for the last 12 months
    results = db.session.query(
        extract('year', Payment.created_at).label('year'),
        extract('month', Payment.created_at).label('month'),
        func.sum(Payment.amount).label('total')
    ).filter(
        Payment.status == 'completed',
        Payment.created_at.isnot(None)
    ).group_by(
        extract('year', Payment.created_at),
        extract('month', Payment.created_at)
    ).order_by(
        extract('year', Payment.created_at),
        extract('month', Payment.created_at)
    ).all()

    # Build a dict of month -> revenue
    monthly_data = {}
    for row in results:
        key = f"{int(row.year)}-{int(row.month):02d}"
        monthly_data[key] = float(row.total or 0)

    # Build the last 12 months labels
    labels = []
    values = []
    for i in range(11, -1, -1):
        # Go back i months from now
        month = now.month - i
        year = now.year
        while month <= 0:
            month += 12
            year -= 1
        key = f"{year}-{month:02d}"
        labels.append(key)
        values.append(monthly_data.get(key, 0))

    return jsonify({"success": True, "labels": labels, "values": values})
