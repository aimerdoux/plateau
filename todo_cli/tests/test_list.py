"""Feature 2 test: format_list renders id + done-box + text, and handles empty.

Runs under pytest or directly as a script (python3 test_list.py).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from todo import add_task, format_list


def test_format_list_renders_id_box_text():
    tasks = []
    add_task(tasks, "buy milk")
    add_task(tasks, "write tests")
    tasks[1]["done"] = True
    assert format_list(tasks).splitlines() == ["[ ] #1 buy milk", "[x] #2 write tests"]


def test_format_list_empty():
    assert format_list([]) == "(no tasks)"


if __name__ == "__main__":
    test_format_list_renders_id_box_text()
    test_format_list_empty()
    print("test_list: PASS")
