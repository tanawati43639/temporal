"""example_continued_workflow — continuous dispatcher reference slice.

The main workflow keeps generating new items on an interval and spawns a child
workflow per item, running until a deadline (stop_time). It uses continue-as-new
to bound history, and starts children with ParentClosePolicy.ABANDON so they
survive each continue-as-new. Copy this folder to start a similar process.
"""
