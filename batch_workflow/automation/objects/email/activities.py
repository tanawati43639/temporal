"""Email object (VBO) — send an email as a Temporal activity.

Key points baked in:
- idempotency_key makes retries safe (an activity may run more than once).
- Auth failures are non-retryable (a bad password won't fix itself); transient
  network errors fall through and get retried by the RetryPolicy.
"""

import asyncio
import logging

from temporalio import activity
from temporalio.exceptions import ApplicationError

from automation.models.notify import EmailInput

logger = logging.getLogger(__name__)

# Demo idempotency store. In production use a shared, durable store
# (DB table / Redis) keyed by idempotency_key, not an in-memory set.
_sent_keys: set[str] = set()


@activity.defn
async def send_email(input: EmailInput) -> None:
    if input.idempotency_key in _sent_keys:
        activity.logger.info("email %s already sent — skipping (safe retry)", input.idempotency_key)
        return

    try:
        await _smtp_send(input.to, input.subject, input.body)
    except PermissionError:
        # 4xx-style permanent failure: do not retry.
        raise ApplicationError(
            "SMTP authentication failed",
            type="EmailAuthError",
            non_retryable=True,
        )
    # transient errors (ConnectionError/TimeoutError) propagate -> RetryPolicy retries

    _sent_keys.add(input.idempotency_key)
    activity.logger.info("sent email to %s (attempt %d)", input.to, activity.info().attempt)


async def _smtp_send(to: str, subject: str, body: str) -> None:
    # TODO: replace with real send (aiosmtplib, or Microsoft Graph sendMail).
    await asyncio.sleep(0.2)  # simulate network latency
