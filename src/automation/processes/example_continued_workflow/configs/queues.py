"""Process-local config and dispatcher tuning — NOT workflow input."""

EXAMPLE_CONTINUED_QUEUE = "example-continued-task-queue"
MAX_CONCURRENT_ACTIVITIES = 5

# Dispatcher tuning.
POLL_INTERVAL_SECONDS = 10   # durable sleep between generation polls
ITEMS_PER_POLL = 5          # new items generated each poll
# Polls before continue-as-new. Kept small here so the example demonstrates CAN
# quickly; in production pick it from the ~10,000-event history budget
# (a child start+complete ≈ 4-5 parent events).
ITERATIONS_PER_RUN = 5
