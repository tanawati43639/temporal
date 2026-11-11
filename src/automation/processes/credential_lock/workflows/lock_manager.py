"""CredentialLockWorkflow — semaphore pattern for credential locking.

A long-running workflow that acts as a distributed mutex for a single
credential.  Workers signal ``acquire`` to request exclusive access and
``release`` to give it back.  The workflow keeps a FIFO queue and grants
the lock to the next waiter whenever the current holder releases (or
times out).

The workflow continue-as-news periodically so history stays bounded.

Analogous to Blue Prism's *Acquire Lock / Release Lock* for credentials.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from automation.processes.credential_lock.activities.credential_store import (
        get_credential,
        notify_granted,
    )
    from automation.processes.credential_lock.configs.queues import (
        ITERATIONS_PER_RUN,
    )
    from automation.processes.credential_lock.models.credential import (
        AcquireRequest,
        CredentialInfo,
        GrantedSignal,
        LockEntry,
        LockManagerInput,
        LockStatus,
        ReleaseRequest,
    )


@workflow.defn
class CredentialLockWorkflow:

    def __init__(self) -> None:
        self._holder: LockEntry | None = None
        self._queue: list[AcquireRequest] = []
        self._pending_releases: list[str] = []
        self._pending_acquires: list[AcquireRequest] = []
        self._total_acquires = 0
        self._total_releases = 0
        self._credential_name = ""
        self._lock_timeout_seconds = 300
        self._events = 0
        self._shutdown = False

    # ── Signals ──────────────────────────────────────────────────

    @workflow.signal
    async def acquire(self, request: AcquireRequest) -> None:
        self._pending_acquires.append(request)

    @workflow.signal
    async def release(self, request: ReleaseRequest) -> None:
        self._pending_releases.append(request.requester_workflow_id)

    @workflow.signal
    async def shutdown(self) -> None:
        self._shutdown = True

    # ── Queries ──────────────────────────────────────────────────

    @workflow.query
    def status(self) -> LockStatus:
        return LockStatus(
            credential_name=self._credential_name,
            holder=self._holder,
            queue=[r.requester_workflow_id for r in self._queue],
            total_acquires=self._total_acquires,
            total_releases=self._total_releases,
        )

    # ── Main loop ────────────────────────────────────────────────

    @workflow.run
    async def run(self, input: LockManagerInput) -> LockStatus:
        self._credential_name = input.credential_name
        self._lock_timeout_seconds = input.lock_timeout_seconds

        while not self._shutdown:
            # Wait until something happens or lock times out.
            timeout = timedelta(seconds=self._lock_timeout_seconds) if self._holder else None
            try:
                await workflow.wait_condition(
                    lambda: bool(self._pending_acquires or self._pending_releases or self._shutdown),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                # Lock holder timed out — auto-release.
                if self._holder:
                    workflow.logger.warning(
                        "Lock timeout: auto-releasing from %s", self._holder.workflow_id
                    )
                    self._holder = None
                    self._total_releases += 1

            # Process releases first.
            for wf_id in self._pending_releases:
                if self._holder and self._holder.workflow_id == wf_id:
                    self._holder = None
                    self._total_releases += 1
                else:
                    self._queue = [r for r in self._queue if r.requester_workflow_id != wf_id]
            self._pending_releases.clear()

            # Process new acquire requests.
            for req in self._pending_acquires:
                self._queue.append(req)
            self._pending_acquires.clear()

            # Grant lock to next in queue if available.
            if self._holder is None and self._queue:
                next_req = self._queue.pop(0)
                self._holder = LockEntry(
                    workflow_id=next_req.requester_workflow_id,
                    acquired_at=workflow.now().isoformat(),
                )
                self._total_acquires += 1
                await self._grant_to(next_req)

            self._events += 1

            # Continue-as-new to keep history bounded.
            if self._events >= ITERATIONS_PER_RUN:
                await workflow.wait_condition(workflow.all_handlers_finished)
                workflow.continue_as_new(input)

        return self.status()

    async def _grant_to(self, request: AcquireRequest) -> None:
        """Fetch credential and signal the requester that lock is granted."""
        cred: CredentialInfo = await workflow.execute_activity(
            get_credential,
            request.credential_name,
            start_to_close_timeout=timedelta(seconds=30),
        )
        await workflow.execute_activity(
            notify_granted,
            GrantedSignal(
                credential_name=request.credential_name,
                username=cred.username,
                password=cred.password,
            ),
            args=[request.requester_workflow_id],
            start_to_close_timeout=timedelta(seconds=30),
        )
