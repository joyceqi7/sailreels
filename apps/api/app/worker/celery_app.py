from celery import Celery

from app.core.config import Settings, get_settings


def create_celery_app(settings: Settings) -> Celery:
    app = Celery("sailreels", broker=settings.celery_broker_url or settings.redis_url,
                 include=["app.worker.tasks"])
    # The webhook retry sweep is NOT gated on TOKEN_REFRESH_ENABLED: an unapplied payment or
    # subscription event must be retried in every environment. The HTTP handler returns 200 on a
    # business failure (so TikTok does not retry-storm us), which makes this sweep load-bearing.
    beat_schedule: dict[str, dict] = {
        "retry-unprocessed-webhooks": {
            "task": "sailreels.webhooks.retry_unprocessed",
            "schedule": settings.webhook_retry_interval_seconds,
            "options": {"expires": settings.webhook_retry_interval_seconds},
        },
    }
    if settings.token_refresh_enabled:
        beat_schedule["scan-due-user-tokens"] = {
            "task": "sailreels.auth.scan_due_tokens",
            "schedule": settings.token_refresh_interval_seconds,
            "options": {"expires": settings.token_refresh_interval_seconds, "queue": "auth"},
        }
    app.conf.update(
        timezone="UTC", enable_utc=True,
        task_serializer="json", accept_content=["json"], result_serializer="json",
        task_ignore_result=True, task_default_queue="default",
        task_routes={"sailreels.auth.*": {"queue": "auth"}},
        worker_prefetch_multiplier=1, broker_connection_retry_on_startup=True,
        # Tasks are small per-user units. A forced loss is rechecked by the next beat scan.
        task_acks_late=True, task_soft_time_limit=60, task_time_limit=90,
        broker_transport_options={"visibility_timeout": 300},
        beat_schedule=beat_schedule,
    )
    return app


celery_app = create_celery_app(get_settings())
