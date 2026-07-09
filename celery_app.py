# =========================================
# CELERY APP CONFIGURATION — BUBBL.OOO
# =========================================
# Broker + Backend: Local Redis (free, unlimited)
# Pool: gevent (1 process, 20 concurrent I/O tasks)
#
# Start with:
#   celery -A celery_app.celery worker --pool=gevent --concurrency=20 --loglevel=info

import os
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')


def make_celery():
    """Create and configure the Celery application."""
    # `include` explicitly imports task modules so their @celery.task functions
    # register with the worker. autodiscover_tasks(['tasks']) alone looks for
    # tasks/tasks.py (related_name='tasks') and MISSES tasks/scrape_tasks.py,
    # which caused: KeyError: 'tasks.scrape_tasks.async_scrape_task'.
    app = Celery('bubbl', include=['tasks.scrape_tasks'])

    app.conf.update(
        # --- BROKER (where tasks are queued) ---
        broker_url=REDIS_URL,

        # --- RESULT BACKEND (where results are stored) ---
        result_backend=REDIS_URL,

        # --- SERIALIZATION ---
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',

        # --- TIMEZONE ---
        timezone='UTC',
        enable_utc=True,

        # --- RELIABILITY ---
        task_acks_late=True,              # Re-deliver task if worker crashes mid-execution
        task_reject_on_worker_lost=True,  # Requeue if worker is killed (OOM, etc.)
        worker_prefetch_multiplier=1,     # Fair scheduling: don't hog tasks

        # --- TASK TRACKING ---
        task_track_started=True,          # Lets us check if a task is "in progress"

        # --- MEMORY SAFETY ---
        worker_max_tasks_per_child=200,   # Restart worker process after 200 tasks (prevents leaks)

        # --- RETRY DEFAULTS ---
        task_default_retry_delay=30,      # Wait 30s before retry
        task_max_retries=3,               # Max 3 retries per task

        # --- RESULT EXPIRY ---
        result_expires=3600,              # Results expire after 1 hour
    )

    # Discover tasks in the 'tasks' package. related_name matches our actual
    # module name (scrape_tasks.py), not the default 'tasks.py'.
    app.autodiscover_tasks(['tasks'], related_name='scrape_tasks')

    return app


celery = make_celery()
