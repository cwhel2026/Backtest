from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "prop_edge",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    broker_connection_retry_on_startup=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "research-health-pulse": {
            "task": "app.worker.tasks.health_pulse",
            "schedule": 300.0,
        },
        "autonomous-prop-hourly": {
            "task": "app.worker.tasks.autonomous_prop_cycle",
            "schedule": 3600.0,
        },
        "paper-forward-tick": {
            "task": "app.worker.tasks.paper_forward_tick",
            "schedule": 20.0,
        },
    },
)