"""Celery application: broker and result_backend use REDIS_URL."""
from celery import Celery

from celery_app import config

app = Celery(
    "bim_bidding",
    broker=config.broker_url,
    backend=config.result_backend,
    include=["tasks.demo", "tasks.extract", "tasks.analyze", "tasks.params", "tasks.framework", "tasks.chapters", "tasks.review", "tasks.kb_ingest"],
)
app.config_from_object(config)
