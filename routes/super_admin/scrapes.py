"""Super Admin — Scrape job management."""
from flask import render_template, request, jsonify
from models.models import db, ScrapeJob
from . import super_admin_bp
from .decorators import super_admin_required


@super_admin_bp.route('/scrapes')
@super_admin_required
def scrapes_page():
    """List failed scrape jobs."""
    failed_scrapes = ScrapeJob.query.filter_by(
        status='failed'
    ).order_by(ScrapeJob.created_at.desc()).all()
    return render_template('super_admin/scrapes.html', scrapes=failed_scrapes)


@super_admin_bp.route('/scrapes/retry', methods=['POST'])
@super_admin_required
def retry_scrape():
    """Reset a failed scrape job to pending."""
    data = request.get_json(silent=True) or {}
    try:
        job_id = int(data.get('job_id'))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid job ID."}), 400

    job = ScrapeJob.query.get(job_id)
    if not job:
        return jsonify({"error": "Scrape job not found."}), 404

    job.status = 'pending'
    job.error_message = None
    db.session.commit()

    return jsonify({"success": True})


@super_admin_bp.route('/scrapes/delete', methods=['POST'])
@super_admin_required
def delete_scrape():
    """Delete a scrape job."""
    data = request.get_json(silent=True) or {}
    try:
        job_id = int(data.get('job_id'))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid job ID."}), 400

    job = ScrapeJob.query.get(job_id)
    if not job:
        return jsonify({"error": "Scrape job not found."}), 404

    db.session.delete(job)
    db.session.commit()

    return jsonify({"success": True})
