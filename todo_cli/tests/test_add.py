"""Feature 1 test: adding a task assigns sequential ids and stores text + done flag.

Runs under pytest (test_* function) or directly as a script (python3 test_add.py).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from todo import add_task


def test_add_assigns_sequential_ids():
    tasks = []
    a = add_task(tasks, "write tests")
    b = add_task(tasks, "ship it")
    assert a["id"] == 1 and a["text"] == "write tests" and a["done"] is False
    assert b["id"] == 2
    assert len(tasks) == 2


if __name__ == "__main__":
    test_add_assigns_sequential_ids()
    print("test_add: PASS")
