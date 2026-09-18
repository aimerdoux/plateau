"""Feature 4 test: save_tasks/load_tasks round-trip; missing file loads as [].

Runs under pytest or directly as a script (python3 test_persist.py).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from todo import add_task, load_tasks, save_tasks


def test_save_then_load_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "todos.json")
        tasks = []
        add_task(tasks, "alpha")
        add_task(tasks, "beta")
        save_tasks(path, tasks)
        loaded = load_tasks(path)
        assert loaded == tasks
        assert loaded[0]["text"] == "alpha" and loaded[1]["id"] == 2


def test_load_missing_returns_empty():
    assert load_tasks("/nonexistent/path/todos.json") == []


if __name__ == "__main__":
    test_save_then_load_roundtrip()
    test_load_missing_returns_empty()
    print("test_persist: PASS")
