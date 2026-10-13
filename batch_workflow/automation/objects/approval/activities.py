"""Approval object (VBO) — activities that handle notifications and
side effects for the human-in-the-loop approval process.

All I/O lives here (send email, update DB, log audit trail).
The workflow (process) never does I/O directly.
"""

import asyncio
import logging

from temporalio import activity
from temporalio.exceptions import ApplicationError

from automation.models.approval import ApprovalRequest

logger = logging.getLogger(__name__)


@activity.defn
async def send_approval_request(request: ApprovalRequest) -> str:
    """Notify the approver that a decision is needed.

    In production: send email/Slack/Teams message with an approval link
    pointing back to your app (which then signals the workflow).
    """
    # TODO: Replace with real notification (Graph API / Slack webhook / etc.)
    await asyncio.sleep(0.2)

    approval_link = (
        f"https://approval.yourcompany.com/decide"
        f"?workflow_id=approval-{request.requester}-{request.request_type}"
    )
    activity.logger.info(
        "Sent approval request to %s: '%s' (link: %s)",
        request.approver,
        request.description,
        approval_link,
    )
    return approval_link


@activity.defn
async def send_reminder(request: ApprovalRequest, reminder_number: int) -> None:
    """Send a follow-up reminder to the approver."""
    await asyncio.sleep(0.1)
    activity.logger.info(
        "Reminder #%d sent to %s for request from %s",
        reminder_number,
        request.approver,
        request.requester,
    )


@activity.defn
async def escalate_request(
    request: ApprovalRequest, escalation_level: int
) -> str:
    """Escalate to the next level of management.

    Returns the new approver (e.g. the manager's manager).
    """
    await asyncio.sleep(0.1)

    # In production: look up the org chart / escalation matrix
    new_approver = f"level{escalation_level}-manager@example.com"
    activity.logger.info(
        "Escalated request from %s to %s (level %d)",
        request.requester,
        new_approver,
        escalation_level,
    )
    return new_approver


@activity.defn
async def apply_approved_action(request: ApprovalRequest) -> None:
    """Execute the approved action (e.g. book leave, create PO).

    Idempotency note: use a unique key (workflow_id + request_type) so
    retries don't apply the action twice.
    """
    await asyncio.sleep(0.2)
    activity.logger.info(
        "Action applied: %s for %s (type=%s, amount=%.2f)",
        request.description,
        request.requester,
        request.request_type,
        request.amount,
    )


@activity.defn
async def send_decision_notification(
    request: ApprovalRequest, approved: bool, comment: str
) -> None:
    """Notify the requester of the final decision."""
    await asyncio.sleep(0.1)
    status = "APPROVED" if approved else "REJECTED"
    activity.logger.info(
        "Notified %s: your %s request was %s. Comment: %s",
        request.requester,
        request.request_type,
        status,
        comment or "(none)",
    )
