"""Process-local configuration: the task queue this process runs on, plus
worker tuning. Keep queue names unique per resource profile so processes that
scale differently never share a queue.
"""

BATCH_QUEUE = "example-batch-task-queue"

# Worker tuning for this process.
MAX_CONCURRENT_ACTIVITIES = 5
