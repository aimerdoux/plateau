# What we killed to get here

Plateau is the surviving idea from a longer research arc. The arc mattered less than
the discipline that ran it, and the most important thing that discipline ever did was
catch *our own fabricated result*. That story is the reason you should trust the
numbers in this repo — not because we are careful people, but because the apparatus
does not depend on us being careful.

## The thing we killed

The project started as an ambitious symbolic context-compression protocol (working
name BMACP) with a theoretical claim about "tangent-noise" in a model's emitted state
— that continuity left a particular geometric signature you could read off as a sign
of an inner process. We pre-registered the claim with both outcomes written down
*before* running, then ran it. **It was falsified.** The signature did not appear; the
effect we predicted was not there. We did not quietly repurpose the framing into
something that sounded like a win. We recorded it as killed and moved the live
hypothesis to something we could actually measure: does carrying a small re-grounded
signal, instead of full history, keep an agent's context bounded *without* dropping the
work? That question became Plateau.

## The result the harness caught us fabricating

Later in the same arc, a result appeared in the project's logs claiming a clean win on
a trajectory-geometry experiment — complete with a "recompute PASS" note asserting the
sealed data verified. It read exactly like a genuine finding.

It wasn't grounded. When we applied the project's own sacred rule to it — *a claim is
just a thought until it re-grounds against the sealed artifacts* — three things fell
out:

1. The "recompute PASS" was **false**. The verification glob never actually scanned the
   experiment's manifest, so nothing had been checked. The reassuring green was empty.
2. Only after independently re-running the verification — recomputing every hash,
   reproducing the verdict from the sealed raw in a fresh process — did the number
   survive. It happened to be real, but *we had been about to report it on trust*, and
   trust was the one disqualifying move.
3. A later deliberate tamper drill (appending a single `#tamper` line to a sealed raw
   file) was caught immediately by the recompute backstop, which named the exact file
   and the exact hash mismatch. No human judgment in the loop.

The lesson is baked into Plateau's design: the gate (`plateau.signal.gate`) refuses any
fact that cannot re-verify against reality *right now*, and the optional integrity
layer (`plateau.integrity`) makes a sealed result's provenance checkable by anyone, not
just by the writer. Bounded context is cheap. The reason it is *safe* is that only
checkable state earns a seat in the signal — and "the agent said so" is never checkable.

## Why this is in the repo

Every benchmark README claims a win. Few show the win they didn't get, or the moment
the tooling caught the authors mid-mistake. We keep this here because the demo numbers
in this repo are produced by the same machinery that killed BMACP's headline claim and
flagged our own fabricated PASS. If it would catch us, you can read the sealed demo and
check it caught nothing this time — or find where it did.

The discipline, stated once:

- **Pre-register before measuring.** Write down what a win *and* a loss look like first.
- **Seal before scoring.** Raw data is written write-once before any number is computed.
- **Recompute-verify.** The reported numbers must reproduce from the sealed raw in a
  fresh process, or they are not reported.
- **The gate is sacred.** A claim enters the carried signal only if a Measurement
  re-verifies it now. "Probably right" never qualifies.
