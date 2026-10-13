"""NotifyWorkflow — example process that orchestrates external objects:
uploads a report to SharePoint, then emails the recipient a link.

Shows the activity-call hygiene the skill recommends: explicit timeouts,
heartbeat timeout for the long upload, and a RetryPolicy that treats auth
failures as non-retryable.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from automation.models.notify import EmailInput, NotifyInput, UploadInput
    from automation.objects.email.activities import send_email


@workflow.defn
class NotifyWorkflow:
    @workflow.run
    async def run(self, input: NotifyInput) -> str:
        # 1) Upload the report. The SharePoint activity is class-based, so it is
        #    referenced by its registered name rather than by import.
        path = await workflow.execute_activity(
            "sharepoint_upload_file",
            UploadInput(
                site="finance",
                folder="reports",
                filename=input.report_name,
                source_ref=input.report_ref,
            ),
            start_to_close_timeout=timedelta(minutes=5),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )

        # 2) Email a link. idempotency_key derived from the workflow id makes a
        #    retried send safe; EmailAuthError is non-retryable.
        await workflow.execute_activity(
            send_email,
            EmailInput(
                to=input.recipient,
                subject=f"Report ready: {input.report_name}",
                body=f"Your report is available at: {path}",
                idempotency_key=f"{workflow.info().workflow_id}-notify",
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(
                maximum_attempts=5,
                non_retryable_error_types=["EmailAuthError"],
            ),
        )

        return path
