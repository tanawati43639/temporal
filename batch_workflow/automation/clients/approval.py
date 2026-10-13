"""Client for the human-in-the-loop approval workflow.

Shows how to:
  1. Start the workflow
  2. Query current state (dashboard)
  3. Update the request while pending
  4. Signal a decision (approve / reject)

Run:
  # 1) Start the workflow
  python -m automation.clients.approval start

  # 2) Check status (query — read-only, no side effects)
  python -m automation.clients.approval status

  # 3) Update amount while pending (update — synchronous, returns a reply)
  python -m automation.clients.approval update-amount 5000

  # 4) Approve (signal — fire-and-forget)
  python -m automation.clients.approval approve --comment "Looks good"

  # 4b) Or reject
  python -m automation.clients.approval reject --comment "Over budget"

  # 5) Wait for result
  python -m automation.clients.approval result
"""

import argparse
import asyncio

from temporalio.client import Client

from automation.config.queues import APPROVAL_QUEUE
from automation.config.settings import TEMPORAL_ADDRESS
from automation.models.approval import ApprovalDecision, ApprovalRequest
from automation.processes.approval.approval_workflow import ApprovalWorkflow

WORKFLOW_ID = "approval-demo-leave-001"


async def cmd_start(args: argparse.Namespace) -> None:
    """Start a new approval workflow."""
    client = await Client.connect(TEMPORAL_ADDRESS)

    request = ApprovalRequest(
        requester=args.requester,
        request_type=args.type,
        description=args.description,
        approver=args.approver,
        amount=args.amount,
        timeout_hours=args.timeout,
    )

    handle = await client.start_workflow(
        ApprovalWorkflow.run,
        request,
        id=WORKFLOW_ID,
        task_queue=APPROVAL_QUEUE,
    )
    print(f"Workflow started: {handle.id}")
    print(f"  Requester : {request.requester}")
    print(f"  Approver  : {request.approver}")
    print(f"  Type      : {request.request_type}")
    print(f"  Amount    : {request.amount}")
    print(f"  Timeout   : {request.timeout_hours}h")
    print()
    print("Now waiting for a human decision...")
    print(f"  Approve : python -m automation.clients.approval approve")
    print(f"  Reject  : python -m automation.clients.approval reject")
    print(f"  Status  : python -m automation.clients.approval status")


async def cmd_status(args: argparse.Namespace) -> None:
    """Query the current approval state (read-only)."""
    client = await Client.connect(TEMPORAL_ADDRESS)
    handle = client.get_workflow_handle(WORKFLOW_ID)

    state = await handle.query(ApprovalWorkflow.get_state)
    print(f"Status: {state.status}")
    print(f"Escalation level: {state.escalation_level}")
    if state.request:
        print(f"Amount: {state.request.amount}")
    print(f"History ({len(state.history)} events):")
    for i, entry in enumerate(state.history, 1):
        print(f"  {i}. {entry}")


async def cmd_update_amount(args: argparse.Namespace) -> None:
    """Update the requested amount (synchronous — returns confirmation)."""
    client = await Client.connect(TEMPORAL_ADDRESS)
    handle = client.get_workflow_handle(WORKFLOW_ID)

    result = await handle.execute_update(
        ApprovalWorkflow.update_amount,
        args.new_amount,
    )
    print(f"Update result: {result}")


async def cmd_decide(args: argparse.Namespace, approved: bool) -> None:
    """Signal the workflow with a human decision."""
    client = await Client.connect(TEMPORAL_ADDRESS)
    handle = client.get_workflow_handle(WORKFLOW_ID)

    decision = ApprovalDecision(
        approved=approved,
        comment=args.comment,
        decided_by=args.decided_by,
    )
    await handle.signal(ApprovalWorkflow.decide, decision)
    action = "APPROVED" if approved else "REJECTED"
    print(f"Decision sent: {action}")
    print(f"  Comment   : {decision.comment}")
    print(f"  Decided by: {decision.decided_by}")


async def cmd_result(args: argparse.Namespace) -> None:
    """Wait for the workflow to complete and print the result."""
    client = await Client.connect(TEMPORAL_ADDRESS)
    handle = client.get_workflow_handle(WORKFLOW_ID)

    print("Waiting for workflow to complete...")
    result = await handle.result()
    print(f"Final result: {result}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Human-in-the-loop approval client")
    sub = parser.add_subparsers(dest="command", required=True)

    # start
    p_start = sub.add_parser("start", help="Start a new approval workflow")
    p_start.add_argument("--requester", default="alice@example.com")
    p_start.add_argument("--approver", default="bob-manager@example.com")
    p_start.add_argument("--type", default="leave", help="leave | purchase | access")
    p_start.add_argument("--description", default="Annual leave: 25-29 Dec 2026")
    p_start.add_argument("--amount", type=float, default=0.0)
    p_start.add_argument("--timeout", type=int, default=72, help="hours before escalation")

    # status (query)
    sub.add_parser("status", help="Query current approval state")

    # update-amount (update)
    p_update = sub.add_parser("update-amount", help="Update the requested amount")
    p_update.add_argument("new_amount", type=float)

    # approve (signal)
    p_approve = sub.add_parser("approve", help="Approve the request")
    p_approve.add_argument("--comment", default="")
    p_approve.add_argument("--decided-by", default="bob-manager@example.com")

    # reject (signal)
    p_reject = sub.add_parser("reject", help="Reject the request")
    p_reject.add_argument("--comment", default="")
    p_reject.add_argument("--decided-by", default="bob-manager@example.com")

    # result
    sub.add_parser("result", help="Wait for final result")

    args = parser.parse_args()

    if args.command == "start":
        asyncio.run(cmd_start(args))
    elif args.command == "status":
        asyncio.run(cmd_status(args))
    elif args.command == "update-amount":
        asyncio.run(cmd_update_amount(args))
    elif args.command == "approve":
        asyncio.run(cmd_decide(args, approved=True))
    elif args.command == "reject":
        asyncio.run(cmd_decide(args, approved=False))
    elif args.command == "result":
        asyncio.run(cmd_result(args))


if __name__ == "__main__":
    main()
