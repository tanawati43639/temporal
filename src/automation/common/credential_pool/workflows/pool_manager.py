"""CredentialPoolWorkflow — manages a pool of credentials.

One workflow per pool (e.g. "SAP_POOL" with SAP_01, SAP_02, SAP_03).
Workers signal ``acquire`` to get any available credential and
``release`` to return it.  Requests queue FIFO when all credentials
are in use.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from automation.common.credential_pool.activities.pool_activities import (
        fetch_credential,
        signal_requester_granted,
    )
    from automation.common.credential_pool.configs.pool_config import (
        ITERATIONS_PER_RUN,
    )
    from automation.common.credential_pool.models.pool import (
        AcquireSignal,
        CredentialInfo,
        GrantedSignal,
        PoolConfig,
        PoolEntry,
        PoolStatus,
        ReleaseSignal,
        WaitingRequest,
    )


@workflow.defn
class CredentialPoolWorkflow:

    def __init__(self) -> None:
        self._pool: list[PoolEntry] = []
        self._queue: list[WaitingRequest] = []
        self._pending_acquires: list[AcquireSignal] = []
        self._pending_releases: list[ReleaseSignal] = []
        self._total_acquires = 0
        self._total_releases = 0
        self._pool_name = ""
        self._lock_timeout_seconds = 300
        self._events = 0
        self._shutdown = False

    # ── Signals ──────────────────────────────────────────────────

    @workflow.signal
    async def acquire(self, request: AcquireSignal) -> None:
        self._pending_acquires.append(request)

    @workflow.signal
    async def release(self, request: ReleaseSignal) -> None:
        self._pending_releases.append(request)

    @workflow.signal
    async def shutdown(self) -> None:
        self._shutdown = True

    # ── Queries ──────────────────────────────────────────────────

    @workflow.query
    def status(self) -> PoolStatus:
        return PoolStatus(
            pool_name=self._pool_name,
            credentials=list(self._pool),
            queue=[w.requester_workflow_id for w in self._queue],
            total_acquires=self._total_acquires,
            total_releases=self._total_releases,
        )

    # ── Main loop ────────────────────────────────────────────────

    @workflow.run
    async def run(self, config: PoolConfig) -> PoolStatus:
        self._pool_name = config.pool_name
        self._lock_timeout_seconds = config.lock_timeout_seconds

        # Initialize pool entries (preserve state on continue-as-new via config).
        if not self._pool:
            self._pool = [PoolEntry(credential_name=name) for name in config.credential_names]

        while not self._shutdown:
            timeout = timedelta(seconds=self._lock_timeout_seconds) if self._any_locked() else None
            try:
                await workflow.wait_condition(
                    lambda: bool(self._pending_acquires or self._pending_releases or self._shutdown),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                self._auto_release_expired()

            self._process_releases()
            await self._process_acquires()

            self._events += 1
            if self._events >= ITERATIONS_PER_RUN:
                await workflow.wait_condition(workflow.all_handlers_finished)
                workflow.continue_as_new(config)

        return self.status()

    # ── Internal ─────────────────────────────────────────────────

    def _any_locked(self) -> bool:
        return any(e.is_locked for e in self._pool)

    def _find_free(self) -> PoolEntry | None:
        for entry in self._pool:
            if not entry.is_locked:
                return entry
        return None

    def _auto_release_expired(self) -> None:
        now = workflow.now()
        for entry in self._pool:
            if not entry.is_locked or not entry.acquired_at:
                continue
            from datetime import datetime
            acquired = datetime.fromisoformat(entry.acquired_at)
            if (now - acquired).total_seconds() >= self._lock_timeout_seconds:
                workflow.logger.warning(
                    "Auto-release %s from %s (timeout)", entry.credential_name, entry.holder_workflow_id
                )
                entry.holder_workflow_id = ""
                entry.acquired_at = ""
                self._total_releases += 1

    def _process_releases(self) -> None:
        for rel in self._pending_releases:
            for entry in self._pool:
                if entry.holder_workflow_id == rel.requester_workflow_id and entry.credential_name == rel.credential_name:
                    entry.holder_workflow_id = ""
                    entry.acquired_at = ""
                    self._total_releases += 1
                    break
            else:
                # Also remove from queue if not yet granted.
                self._queue = [w for w in self._queue if w.requester_workflow_id != rel.requester_workflow_id]
        self._pending_releases.clear()

    async def _process_acquires(self) -> None:
        for acq in self._pending_acquires:
            free = self._find_free()
            if free:
                free.holder_workflow_id = acq.requester_workflow_id
                free.acquired_at = workflow.now().isoformat()
                self._total_acquires += 1
                await self._grant(acq.requester_workflow_id, free.credential_name)
            else:
                self._queue.append(WaitingRequest(
                    requester_workflow_id=acq.requester_workflow_id,
                    requested_at=workflow.now().isoformat(),
                ))
        self._pending_acquires.clear()

        # Grant to queued waiters if credentials freed up.
        granted: list[WaitingRequest] = []
        for waiter in self._queue:
            free = self._find_free()
            if not free:
                break
            free.holder_workflow_id = waiter.requester_workflow_id
            free.acquired_at = workflow.now().isoformat()
            self._total_acquires += 1
            await self._grant(waiter.requester_workflow_id, free.credential_name)
            granted.append(waiter)
        for w in granted:
            self._queue.remove(w)

    async def _grant(self, requester_wf_id: str, credential_name: str) -> None:
        cred: CredentialInfo = await workflow.execute_activity(
            fetch_credential,
            credential_name,
            start_to_close_timeout=timedelta(seconds=30),
        )
        await workflow.execute_activity(
            signal_requester_granted,
            GrantedSignal(
                credential_name=cred.name,
                username=cred.username,
                password=cred.password,
            ),
            args=[requester_wf_id],
            start_to_close_timeout=timedelta(seconds=30),
        )
