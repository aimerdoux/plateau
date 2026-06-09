# Security Policy

## Reporting a vulnerability

Please report security issues privately via GitHub's **"Report a vulnerability"** (Security →
Advisories) on this repository, rather than opening a public issue. We'll acknowledge within a
few days and coordinate a fix and disclosure.

## Scope notes specific to Plateau

- **The core has zero third-party runtime dependencies** (stdlib only), which keeps the supply-chain
  surface minimal. The optional `[demo]` extra (numpy/matplotlib) is for charts only and is never
  imported by the core.
- **The agency layer is code-constrained for blast radius.** In `--mode write` it stages changes in a
  path-scoped working area, runs them through the gate, and **emits a PR — it never merges, force-pushes,
  or pushes to `main`.** `--mode audit` (the default) is read-only. If you find a path by which the
  agency can mutate a repo outside that contract, treat it as a security issue and report it.
- The integrity layer detects tampering of sealed artifacts (hash-chained manifest + fresh-process
  recompute); it does not *prevent* same-uid modification. The guarantee is **detection + operator
  recompute**, documented in [`INTEGRITY.md`](INTEGRITY.md).
