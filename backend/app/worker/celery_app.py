from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "prop_edge",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.worker.tasks"],
)

REALTIME_QUEUE = "realtime"
RESEARCH_QUEUE = "research"
AI_ARENA_QUEUE = "ai_arena"

celery_app.conf.update(
    broker_connection_retry_on_startup=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_default_queue=RESEARCH_QUEUE,
    task_routes={
        "app.worker.tasks.live_lab_stream_ingest": {"queue": REALTIME_QUEUE},
        "app.worker.tasks.live_lab_forward_tick": {"queue": REALTIME_QUEUE},
        "app.worker.tasks.paper_forward_tick": {"queue": REALTIME_QUEUE},
        "app.worker.tasks.health_pulse": {"queue": REALTIME_QUEUE},
        "app.worker.tasks.run_backtest_task": {"queue": RESEARCH_QUEUE},
        "app.worker.tasks.run_data_ingestion": {"queue": RESEARCH_QUEUE},
        "app.worker.tasks.run_prop_search_job": {"queue": RESEARCH_QUEUE},
        "app.worker.tasks.run_ai_hypothesis_task": {"queue": RESEARCH_QUEUE},
        "app.worker.tasks.autonomous_prop_cycle": {"queue": RESEARCH_QUEUE},
        "app.worker.tasks.ai_arena_scheduler_tick": {"queue": AI_ARENA_QUEUE},
        "app.worker.tasks.ai_researcher_cycle_task": {"queue": AI_ARENA_QUEUE},
    },
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
            "schedule": 60.0,
        },
        "live-lab-stream-ingest": {
            "task": "app.worker.tasks.live_lab_stream_ingest",
            "schedule": 5.0,
        },
        "live-lab-forward-tick": {
            "task": "app.worker.tasks.live_lab_forward_tick",
            "schedule": 15.0,
        },
        "ai-arena-scheduler": {
            "task": "app.worker.tasks.ai_arena_scheduler_tick",
            "schedule": 300.0,
        },
    },
)