from app.worker.celery_app import AI_ARENA_QUEUE, REALTIME_QUEUE, RESEARCH_QUEUE, celery_app


def test_task_queues_isolated():
    routes = celery_app.conf.task_routes or {}
    assert routes["app.worker.tasks.live_lab_stream_ingest"]["queue"] == REALTIME_QUEUE
    assert routes["app.worker.tasks.run_prop_search_job"]["queue"] == RESEARCH_QUEUE
    assert routes["app.worker.tasks.ai_researcher_cycle_task"]["queue"] == AI_ARENA_QUEUE