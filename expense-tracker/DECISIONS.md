# Architectural Decisions

A running log so each turn's choices stay consistent with the ones before.
Each decision notes *why* and which later turn relies on it.

## ADR-001 — Storage schema (Turn 1)

**Language/runtime:** Python 3, standard library only (`json`, `argparse`,
`csv`, `unittest`). No third-party deps.

**Document shape** — one JSON object per store file:

```json
{ "version": 1, "next_id": 1, "entries": [ Entry, ... ] }
```

**Entry shape (v1):**

```json
{
  "id": 1,
  "amount_cents": 1234,
  "date": "2026-06-15",
  "description": "coffee",
  "created_at": "2026-06-15T09:30:00+00:00"
}
```

### Decisions and the future turns they serve

1. **Single JSON document, not JSONL / append-log.**
   Edit (T5), delete (T6), and undo (T12) all load → mutate → rewrite the
   whole set. An append-only log would fight every one of them.

2. **`version` is written into the document from day one.**
   The migration (T13) needs to detect which format data was written under.
   Migrations bump `SCHEMA_VERSION` and rewrite; readers branch on `version`.

3. **Stable integer `id`, assigned from a doc-level `next_id` that only
   increments.** Deletes never reclaim an id. T5/T6/T12 reference entries by
   id; array index would not survive a delete.

4. **`amount_cents` is a signed `int` (minor units), never a float.**
   T9 summary stats and T10 CSV export must not accumulate float error.
   Parsing `"$12.34" → 1234` happens at the CLI boundary (T2), not here.

5. **`date` stored canonically as `"YYYY-MM-DD"` (validated via
   `date.fromisoformat`).** Zero-padded ISO strings sort lexicographically =
   chronologically, so T8 date-range filtering is a plain string comparison
   (`start <= e["date"] <= end`). *Display* formatting is a separate concern,
   configurable in T11 — storage stays canonical regardless.

6. **`created_at` (record time) is distinct from `date` (expense time).**
   Two genuinely different facts; `created_at` also gives undo/audit (T12) a
   timestamp and a stable sort tiebreaker.

7. **Reader must tolerate missing fields.**
   T7 adds `tags` by *extending* the entry: new field defaults to `[]` when
   absent, so v1 records written by T4 stay readable and the change does not
   break persistence.

8. **No per-entry `currency`; v1 is single-currency.**
   Deliberate omission (no speculative features). Currency, if ever needed,
   is a display/config concern (T11) or a schema migration (T13) — not v1.

### Invariants any later turn must preserve
- `next_id` is strictly greater than every existing `entry["id"]`.
- Every entry validates: int `amount_cents`, ISO `date`, non-empty
  `description`.
- The document always carries the `version` it was written under.
