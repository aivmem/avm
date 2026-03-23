"""Notification Service REST API using FastAPI."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, status, BackgroundTasks
from fastapi.responses import JSONResponse

from .models import (
    NotificationMessage,
    NotificationType,
    NotificationPriority,
    HealthStatus,
    EmailPayload,
)
from .redis_client import queue
from .processor import processor
from .config import settings
from .logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    # Startup: start the processor in background
    logger.info(f"Starting {settings.service_name} v{settings.service_version}")
    task = asyncio.create_task(processor.run())
    yield
    # Shutdown: stop the processor
    processor.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("Service shutdown complete")


app = FastAPI(
    title="Notification Service",
    description="A service for processing notification messages from Redis queue",
    version=settings.service_version,
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthStatus)
def health_check():
    """Health check endpoint."""
    redis_connected = queue.is_connected()
    queue_length = queue.queue_length() if redis_connected else -1

    status_str = "healthy" if redis_connected else "degraded"

    return HealthStatus(
        status=status_str,
        redis_connected=redis_connected,
        queue_length=queue_length,
    )


@app.get("/")
def root():
    """Root endpoint with service info."""
    return {
        "service": settings.service_name,
        "version": settings.service_version,
        "status": "running",
    }


@app.get("/stats")
def get_stats():
    """Get processor statistics."""
    return {
        "processor": processor.stats,
        "queue_length": queue.queue_length(),
    }


@app.post("/notifications/email", status_code=status.HTTP_202_ACCEPTED)
def submit_email_notification(
    email: EmailPayload,
    priority: NotificationPriority = NotificationPriority.NORMAL,
):
    """Submit an email notification to the queue."""
    notification_id = str(uuid.uuid4())

    message = NotificationMessage(
        id=notification_id,
        type=NotificationType.EMAIL,
        priority=priority,
        payload=email.model_dump(),
    )

    if queue.enqueue(message):
        return {
            "notification_id": notification_id,
            "status": "queued",
            "type": "email",
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to queue notification - Redis unavailable",
        )


@app.post("/notifications", status_code=status.HTTP_202_ACCEPTED)
def submit_notification(message: NotificationMessage):
    """Submit a raw notification message to the queue."""
    if queue.enqueue(message):
        return {
            "notification_id": message.id,
            "status": "queued",
            "type": message.type,
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to queue notification - Redis unavailable",
        )
