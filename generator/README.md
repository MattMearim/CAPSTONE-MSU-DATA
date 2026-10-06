# Synthetic Engineering Data Generator

Produces operational events for testing the decision-support system. Each
event is a waveform capture and an event log that share one `event_id`.
Each run also emits the procedure documents the Level 3 engine retrieves.
Every record validates against `schemas/`.

Standard library only. No installation needed.

## Running it

```
python3 -m generator                                   # 30 events, seed 42
python3 -m generator --seed 7 --events 90
python3 -m generator --domains rf plc
python3 -m generator --domains rf --scenario field_collapse --events 5
python3 -m generator --list                            # show every scenario
```

Output goes to `data/generated/seed-<seed>/`:

- `records/*.json`: the canonical records. This is what the system ingests.
- `ground_truth.json`: which scenario each event really was, when the
  fault happened, and which documents apply. Use it to score the system.
  The system itself must never read it.

The same seed and arguments always produce identical files.

## What it generates

| Field | Asset | Scenarios |
|---|---|---|
| rf | RF cavity station, 10 kHz capture | normal, field collapse, vacuum burst and arc, phase instability, reflected-power sensor glitch (false trip) |
| mechanical | Cooling pump skid, 2 kHz vibration | normal, rotor imbalance, bearing defect, cavitation |
| plc | Cooling interlock rack, 10 Hz | normal, low-flow interlock, stale sensor, communication dropout, chattering switch (false trip) |

Several scenarios are deliberately hard: two are false trips, one has no
alarm at all until late, and one looks like missing data. Per-event
parameters are randomized, and a few channels get short unrelated gaps.

Procedure documents: 12 fictional procedures, 4 per field. Each field has
one superseded revision whose limits conflict with the current one, to
test that retrieval prefers the current revision.

## Adding a field or a scenario

The engine (`engine.py`) contains no field-specific code. Everything is in
config:

- `scenarios/<field>.json`: assets, channels, and scenarios
- `documents/<field>.json`: procedure documents

To add a field, add one file to each folder. No Python changes.

A channel's `baseline` is a list of components:
`constant`, `sine`, `noise`, `drift`, `random_walk`.

A scenario's `effects` change a channel around the fault time
(`delay_s` is relative to the fault and may be negative):
`step`, `ramp`, `exp_decay`, `spike`, `oscillation`, `noise_burst`,
`dropout` (missing samples), `freeze` (stuck reading).

Any number can instead be a range `{"min": a, "max": b}`, a list
`{"choice": [...]}`, or a reference to a sampled configuration value
`{"ref": "name", "scale": k}`.

A scenario's `events` are the discrete log entries, with `offset_s`
relative to the fault and optional `jitter_s`.

## Limits

- The signal shapes are plausible illustrations, not physics simulations.
  Numbers, thresholds and sequences are invented and need review by
  someone who knows the real systems.
- Each event is independent. There are no long-term trends across events
  and no faults that span several assets.
- One asset per event, one fault per event.
