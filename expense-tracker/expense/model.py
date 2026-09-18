"""Core data model for the expense tracker.

Turn 1 — the load-bearing storage decision. Everything later builds on the
shapes and invariants defined here. See ../DECISIONS.md for the rationale.

This module is pure and in-memory: it defines the schema and the operations
that mutate an in-memory ``Store`` dict. Persisting that dict to disk is Turn 4.
"""

from __future__ import annotations

from datetime import date as _date, datetime, timezone
from typing import Any, TypedDict

# Bump this only inside a migration (Turn 13). The on-disk document always
# carries the version it was written under so a reader can tell formats apart.
SCHEMA_VERSION = 1


class Entry(TypedDict):
    id: int  # stable; assigned from Store["next_id"], never reused after delete
    amount_cents: int  # signed integer minor units — never a float
    date: str  # canonical ISO 8601 calendar date, "YYYY-MM-DD"
    description: str
    created_at: str  # ISO 8601 UTC timestamp of when the entry was recorded


class Store(TypedDict):
    version: int
    next_id: int
    entries: list[Entry]


def new_store() -> Store:
    """An empty store stamped with the current schema version."""
    return {"version": SCHEMA_VERSION, "next_id": 1, "entries": []}


# --- validation -----------------------------------------------------------
# Validate at the point data enters the store so the on-disk document
# (Turn 4) can be trusted on read-back without re-checking every field.


def _validate_amount_cents(value: Any) -> int:
    # bool is a subclass of int; reject it so True/False can't slip in as 1/0.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("amount_cents must be an int in minor units, not a float")
    return value


def _validate_date(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("date must be a 'YYYY-MM-DD' string")
    try:
        # fromisoformat both validates and requires zero-padded canonical form,
        # which is what makes lexicographic date-range queries (Turn 8) sound.
        _date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"date must be a valid ISO 8601 date: {value!r}") from exc
    return value


def _validate_description(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("description must be a string")
    text = value.strip()
    if not text:
        raise ValueError("description must not be empty")
    return text


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --- operations -----------------------------------------------------------


def add_entry(
    store: Store,
    amount_cents: int,
    date: str,
    description: str,
    created_at: str | None = None,
) -> Entry:
    """Append a validated entry and advance the id counter.

    ``next_id`` only ever increments — deleting an entry (Turn 6) does not
    reclaim its id, which keeps ids stable for edit/delete/undo to reference.
    """
    entry: Entry = {
        "id": store["next_id"],
        "amount_cents": _validate_amount_cents(amount_cents),
        "date": _validate_date(date),
        "description": _validate_description(description),
        "created_at": created_at or _now_iso(),
    }
    store["entries"].append(entry)
    store["next_id"] += 1
    return entry
