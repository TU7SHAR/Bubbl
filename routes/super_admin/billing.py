"""Super Admin — Revenue & Billing."""
from flask import render_template, current_app
from models.models import Payment, Organization
from . import super_admin_bp
from .decorators import super_admin_required


@super_admin_bp.route('/billing')
@super_admin_required
def billing_page():
    """Revenue metrics and payment history."""
    plan_price = current_app.config.get('PLAN_PRICE_INR', {'free': 0, 'starter': 499, 'growth': 1499, 'pro': 4999})

    all_orgs = Organization.query.all()
    plan_counts = {'free': 0, 'starter': 0, 'growth': 0, 'pro': 0}
    for o in all_orgs:
        plan_counts[o.plan or 'free'] = plan_counts.get(o.plan or 'free', 0) + 1

    active_subs = sum(c for p, c in plan_counts.items() if p != 'free')
    mrr = sum(plan_counts.get(p, 0) * price for p, price in plan_price.items())
    arr = mrr * 12

    all_payments = Payment.query.filter_by(status='completed').order_by(Payment.created_at.desc()).limit(200).all()
    total_revenue = sum(p.amount or 0 for p in all_payments)

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
        })

    return render_template('super_admin/billing.html',
        mrr=mrr, arr=arr, active_subscriptions=active_subs,
        total_revenue=total_revenue, revenue_by_plan=revenue_by_plan,
        recent_payments=recent_payments, plan_counts=plan_counts,
    )
