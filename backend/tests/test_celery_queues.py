from app.worker.celery_app import REALTIME_QUEUE, RESEARCH_QUEUE, celery_app


def test_live_lab_tasks_on_realtime_queue():
    routes = celery_app.conf.task_routes or {}
    assert routes["app.worker.tasks.live_lab_stream_ingest"]["queue"] == REALTIME_QUEUE
    assert routes["app.worker.tasks.run_prop_search_job"]["queue"] == RESEARCH_QUEUE