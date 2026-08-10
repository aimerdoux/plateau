"""Feature 3 test: mark_done flips the done flag by id and returns the task (or None).

Runs under pytest or directly as a script (python3 test_done.py).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from todo import add_task, mark_done


def test_mark_done_sets_flag_and_returns_task():
    tasks = []
    add_task(tasks, "a")
    add_task(tasks, "b")
    t = mark_done(tasks, 2)
    assert t is not None and t["id"] == 2 and t["done"] is True
    assert tasks[0]["done"] is False  # only #2 flipped


def test_mark_done_missing_id_returns_none():
    assert mark_done([], 99) is None


if __name__ == "__main__":
    test_mark_done_sets_flag_and_returns_task()
    test_mark_done_missing_id_returns_none()
    print("test_done: PASS")
