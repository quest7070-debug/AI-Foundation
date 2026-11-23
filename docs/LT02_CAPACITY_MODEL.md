# LT02 long-term storage capacity model

## Purpose

LT02 is a capacity-planning contract, not a second storage authority.

It does not authorize deletion, change retention, rotate externally owned logs,
or replace LT11 `StorageAdmission`. Existing owner-specific lifecycle,
retention, compaction and admission contracts remain authoritative.

## Evidence classes

Persistent/accumulating surfaces are classified before projection:

1. **Bounded/current-state** — use the implemented cardinality, byte or
   generation ceiling. Do not fabricate annual growth.
2. **Retained request-dependent history** — use accelerated physical
   bytes/operation measurements and explicit planning scenarios.
3. **Owner-retained authority** — preserve according to its authority contract.
   Capacity planning does not invent deletion merely to bound it.
4. **Derived/reclaimable state** — use the owning engine's measured
   lifecycle/reclamation behavior.
5. **External-owner state** — use the external owner's proven bound/lifecycle;
   Foundation does not infer deletion authority from size or age.

## Planning scenarios

The deterministic LT02 scenarios are:

| Scenario | Operations/day |
|---|---:|
| low | 100 |
| nominal | 1,000 |
| high | 10,000 |

These are **declared planning assumptions**, not measured or predicted user
traffic. Their purpose is to make capacity consequences comparable without
pretending that Foundation has production workload-rate evidence.

For a measured coefficient `B`, the unit must remain explicit. A bytes/row coefficient from a synthetic scale fixture is not silently relabelled bytes/operation. A real bytes/operation coefficient requires an accelerated operation-level growth probe.

For an actual operation-level coefficient:

- 30-day planning growth = `B/op × operations/day × 30`
- one-year planning growth = `B/op × operations/day × 365`
- three-year planning growth = `B/op × operations/day × 1095`

Synthetic row-shape coefficients are retained separately as scale/cardinality evidence and are not used as user-operation coefficients.

## Existing physical coefficients

Existing accelerated tests are the measurement authority; LT02 does not create
a second synthetic storage implementation.

Representative 100,000-row Foundation SQLite measurements already recorded by
the long-term audit are approximately:

| Store shape | Physical size | Approx. row-shape coefficient |
|---|---:|---:|
| Guard | 36.2 MB / 100k rows | ~362 B/row |
| Durable Work | 25.4 MB / 100k rows | ~254 B/row |
| Durable Inference | 6.6 MB / 100k rows | ~66 B/row |

A separate disposable accelerated operation-level probe measured retained `guard.effects` growth at approximately **98.660 B/operation** across 20,000 operations. Its low/nominal/high annual scenarios are therefore approximately 3.60 MiB / 34.35 MiB / 343.52 MiB per year at 100 / 1,000 / 10,000 operations/day respectively. These remain declared planning scenarios, not observed production rates.

The same probe measured terminal inference and work pre-cleanup growth, but those rows are lifecycle-bounded by their existing owners; they are not projected as permanent retained growth.

These coefficients describe the tested synthetic row shapes. They are not
production traffic measurements and are not promises that every logical user
operation creates exactly one row.

The projection helper is deterministic so future representative measurements
can be inserted without changing the scenario semantics.

## Existing explicit ceilings and owner bounds

LT02 reuses existing limits rather than creating competing thresholds:

- Foundation JSONL trace: 8 MiB current file plus 3 generations, approximately
  32 MiB total implementation bound.
- Foundation backups: three retained valid generations under the existing
  backup lifecycle contract; byte size depends on the protected generation.
- Push dispatch dedup state: at most 2,048 keys.
- Mongo diagnostic capture: engine-owned 250 MB directory ceiling and 10 MB
  file ceiling, as proven by the later LT10 live audit. The earlier
  observation-derived ~3.6 GiB/year extrapolation is superseded and must not be
  treated as unbounded Mongo diagnostic growth.
- Mongo/Meili/pgvector remain product/engine-owned data/index surfaces.
  LT10 owns their source/index/delete/compaction evidence.
- Docker/model-cache cleanup remains owner-scoped. LT02 size observations do
  not grant generic prune/delete authority.
- Externally opened launchd/llama-swap/ToolHive logs remain under LT05 for
  reopen/rotation/disk-full semantics rather than being mutated by LT02.

## Host capacity ceiling

The canonical write-safety threshold remains LT11
`StorageAdmission`: by default, new admitted canonical writes fail closed below
2 GiB free space.

```foundation-semantic
{"source":"src/ai_foundation/storage_admission.py","subject":"src/ai_foundation/storage_admission.py::CLASS::StorageAdmission@14:0","subject_kind":"SYMBOL","claim_kind":"write_admission_boundary","purpose":"enforce the canonical host free-space admission threshold before new admitted canonical writes begin","ownership":"Foundation owns write admission while owner-specific lifecycle, retention, compaction and deletion contracts remain separate authorities","rationale":"keep capacity planning observational while preserving one canonical operational free-space threshold instead of competing cleanup or admission rules","failure_semantics":"new admitted canonical writes fail closed below 2 GiB free space; capacity planning does not authorize deletion to recover space","side_effects":"NONE","change_impact":"changes must preserve the canonical admission threshold semantics and must not mint deletion or external-owner lifecycle authority","evidence":["tests/test_storage_admission.py"]}
```

This is the operational host ceiling for write admission. LT02 projections are
planning evidence above that boundary; they do not introduce another free-space
threshold.

## Interpretation

A low/nominal/high projection answers:

> If a measured persistent row/operation shape were produced at this declared
> planning rate, what physical growth order should capacity planning expect?

It does **not** answer:

> What traffic will the user actually generate?

Actual rates, when available, may be added as separately labelled observations.
They must never silently replace or be confused with the declared scenarios.
