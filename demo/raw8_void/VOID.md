# VOID collection — harness failure, NOT data

This directory is the FIRST demo8 collection attempt. It is void and is retained only for
auditability (its seal is intact and still verifies).

Every `claude -p` worker died in <1.1s without doing any work: the driver invoked
`--permission-mode bypassPermissions`, which the CLI maps to
`--dangerously-skip-permissions` and refuses under root:

    "--dangerously-skip-permissions cannot be used with root/sudo privileges"

So all 10 workers produced that one error line, all 10 gates failed, and completion was
0/5 in both arms. No hypothesis-relevant measurement exists here — the manipulated
variable (prompt content) was never exercised, because no worker ever read its prompt.

Discarding it is therefore not a re-run for a better number (which the prereg forbids):
there is no number here to improve on. The run is disclosed in the readout, the fix is
`--permission-mode acceptEdits`, and a worker preflight probe was added to the driver so a
dead worker aborts the run in one dispatch instead of ten.
