"""ApprovalWorkflow — human-in-the-loop process.

Demonstrates Temporal's ability to durably wait for a human decision:
  1. Send notification to approver
  2. **Wait** — the workflow sleeps (durably) until a signal arrives or timeout
  3. On signal: apply or reject
  4. On timeout: send reminders, then escalate

Key Temporal features used:
  - @workflow.signal   → receive the human's decision
  - @workflow.query    → inspect current state (for dashboards / UI)
  - @workflow.update   → modify request while waiting (e.g. change amount)
  - workflow.wait_condition(lambda, timeout) → durable wait with deadline
  - workflow.sleep     → durable timer for reminders

This workflow can wait days/weeks — Temporal keeps it alive across server
restarts, worker deploys, and infrastructure failures. That's the whole point.
"""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from automation.models.approval import (
        ApprovalDecision,
        ApprovalRequest,
        ApprovalState,
        ApprovalStatus,
    )
    from automation.objects.approval.activities import (
        apply_approved_action,
        escalate_request,
        send_approval_request,
        send_decision_notification,
        send_reminder,
    )


# How often to send reminders while waiting (hours)
_REMINDER_INTERVAL_HOURS = 24
# Max escalation levels before auto-reject
_MAX_ESCALATION = 2


@workflow.defn
class ApprovalWorkflow:
    """A process that waits for a human to approve or reject a request."""

    def __init__(self) -> None:
        self._state = ApprovalState()

    # ──────────────────────────────────────────────────────────────
    # Signal: the human sends their decision
    # ──────────────────────────────────────────────────────────────
    @workflow.signal
    async def decide(self, decision: ApprovalDecision) -> None:
        """Called when the human clicks approve/reject.

        Signals are fire-and-forget — the sender doesn't wait for a reply.
        The signal just sets state; the main `run` method reacts to it.
        """
        self._state.decision = decision
        self._state.status = (
            ApprovalStatus.APPROVED if decision.approved else ApprovalStatus.REJECTED
        )
        self._state.history.append(
            f"Decision received: {'approved' if decision.approved else 'rejected'}"
            f" by {decision.decided_by or 'unknown'}"
        )

    # ──────────────────────────────────────────────────────────────
    # Query: read current state (for UI / dashboard)
    # ──────────────────────────────────────────────────────────────
    @workflow.query
    def get_state(self) -> ApprovalState:
        """Return full state — read-only, no side effects."""
        return self._state

    @workflow.query
    def get_status(self) -> str:
        """Quick status check."""
        return self._state.status.value

    # ──────────────────────────────────────────────────────────────
    # Update: modify the request while it's still pending
    # ──────────────────────────────────────────────────────────────
    @workflow.update
    async def update_amount(self, new_amount: float) -> str:
        """Change the requested amount (e.g. requester corrects a typo).

        Unlike signals, updates are synchronous — the caller gets a reply.
        The validator runs first; if it rejects, the update is NOT recorded
        in history (saves space and prevents invalid state).
        """
        if self._state.request:
            old = self._state.request.amount
            self._state.request.amount = new_amount
            self._state.history.append(f"Amount updated: {old} -> {new_amount}")
            return f"Amount updated from {old} to {new_amount}"
        return "No request found"

    @update_amount.validator
    def _validate_amount(self, new_amount: float) -> None:
        """Validators are read-only — they must NOT mutate state."""
        if self._state.status != ApprovalStatus.PENDING:
            raise ValueError(f"Cannot update: request is already {self._state.status.value}")
        if new_amount < 0:
            raise ValueError("Amount cannot be negative")

    # ──────────────────────────────────────────────────────────────
    # Main workflow logic
    # ──────────────────────────────────────────────────────────────
    @workflow.run
    async def run(self, request: ApprovalRequest) -> str:
        self._state.request = request
        self._state.status = ApprovalStatus.PENDING
        self._state.history.append(
            f"Request submitted by {request.requester}: {request.description}"
        )

        # 1) Send initial notification to approver
        approval_link = await workflow.execute_activity(
            send_approval_request,
            request,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        self._state.history.append(f"Notification sent to {request.approver}")

        # 2) Wait for human decision — with reminders and escalation
        reminder_count = 0
        while self._state.status == ApprovalStatus.PENDING:
            # Wait for either: signal arrives OR reminder interval elapses
            decided = await workflow.wait_condition(
                lambda: self._state.status != ApprovalStatus.PENDING,
                timeout=timedelta(hours=_REMINDER_INTERVAL_HOURS),
            )

            if decided:
                break  # Human responded — proceed to step 3

            # Timeout reached — still pending
            reminder_count += 1
            total_hours_waited = reminder_count * _REMINDER_INTERVAL_HOURS

            if total_hours_waited >= request.timeout_hours:
                # Escalation or auto-reject
                if self._state.escalation_level < _MAX_ESCALATION:
                    self._state.escalation_level += 1
                    new_approver = await workflow.execute_activity(
                        escalate_request,
                        args=[request, self._state.escalation_level],
                        start_to_close_timeout=timedelta(seconds=30),
                    )
                    self._state.history.append(
                        f"Escalated to {new_approver} (level {self._state.escalation_level})"
                    )
                    # Reset reminder counter for the new approver
                    reminder_count = 0
                else:
                    # Max escalation reached — auto-reject
                    self._state.status = ApprovalStatus.TIMED_OUT
                    self._state.history.append(
                        f"Auto-rejected: no response after {request.timeout_hours}h "
                        f"and {_MAX_ESCALATION} escalation(s)"
                    )
                    break
            else:
                # Send a reminder
                await workflow.execute_activity(
                    send_reminder,
                    args=[request, reminder_count],
                    start_to_close_timeout=timedelta(seconds=30),
                )
                self._state.history.append(f"Reminder #{reminder_count} sent")

        # 3) Act on the decision
        if self._state.status == ApprovalStatus.APPROVED:
            await workflow.execute_activity(
                apply_approved_action,
                request,
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            self._state.history.append("Approved action applied")

        # 4) Notify the requester of the outcome
        comment = self._state.decision.comment if self._state.decision else "Timed out"
        await workflow.execute_activity(
            send_decision_notification,
            args=[
                request,
                self._state.status == ApprovalStatus.APPROVED,
                comment,
            ],
            start_to_close_timeout=timedelta(seconds=30),
        )
        self._state.history.append(f"Requester notified: {self._state.status.value}")

        # 5) Wait for any pending signal/update handlers to finish
        await workflow.wait_condition(workflow.all_handlers_finished)

        return self._state.status.value
