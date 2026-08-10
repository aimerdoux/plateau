"""Tiny todo CLI — built one feature per turn for the Plateau bounded-context demo.

Feature 1: add a task.
"""
from __future__ import annotations

import json
import os
import sys


def add_task(tasks, text):
    """Append a new task and return it. Ids are sequential, 1-based ints."""
    task = {"id": len(tasks) + 1, "text": text, "done": False}
    tasks.append(task)
    return task


def format_list(tasks):
    """Render tasks one per line: '[ ] #1 text' / '[x] #2 text'. Empty -> '(no tasks)'."""
    if not tasks:
        return "(no tasks)"
    return "\n".join(
        f"[{'x' if t['done'] else ' '}] #{t['id']} {t['text']}" for t in tasks
    )


def mark_done(tasks, task_id):
    """Mark the task with this id done. Return it, or None if no such id."""
    for t in tasks:
        if t["id"] == task_id:
            t["done"] = True
            return t
    return None


DEFAULT_PATH = "todos.json"


def load_tasks(path):
    """Load tasks from a JSON file. Missing or empty file -> []."""
    if not os.path.exists(path):
        return []
    with open(path) as f:
        data = f.read().strip()
    return json.loads(data) if data else []


def save_tasks(path, tasks):
    """Write tasks to a JSON file."""
    with open(path, "w") as f:
        json.dump(tasks, f, indent=2)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: todo add <text>")
        return 1
    cmd, rest = argv[0], argv[1:]
    path = os.environ.get("TODO_FILE", DEFAULT_PATH)
    tasks = load_tasks(path)
    if cmd == "add":
        if not rest:
            print("usage: todo add <text>")
            return 1
        t = add_task(tasks, " ".join(rest))
        save_tasks(path, tasks)
        print(f"added #{t['id']}: {t['text']}")
        return 0
    if cmd == "list":
        print(format_list(tasks))
        return 0
    if cmd == "done":
        if not rest:
            print("usage: todo done <id>")
            return 1
        try:
            tid = int(rest[0])
        except ValueError:
            print(f"not an id: {rest[0]}")
            return 1
        t = mark_done(tasks, tid)
        if t is None:
            print(f"no task #{tid}")
            return 1
        save_tasks(path, tasks)
        print(f"done #{t['id']}: {t['text']}")
        return 0
    print(f"unknown command: {cmd}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
