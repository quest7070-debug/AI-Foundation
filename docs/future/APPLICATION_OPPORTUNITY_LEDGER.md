# Application Opportunity Ledger

Last updated: 2026-09-29

## Purpose

Record post-Foundation Application / Agent Layer opportunity decisions so reduced or rejected ideas are not repeatedly re-investigated without new evidence.

This ledger is not part of the AI Foundation completion criteria. Candidate-specific functionality must not be added to Foundation merely because it can reuse Foundation capabilities. Promote a candidate into implementation or architecture records only after its independent value and boundary are established.

## Current decisions

| Candidate | Status | Decision basis | Re-open / next condition |
| --- | --- | --- | --- |
| ChangeProof | REDUCE | Generic change intelligence is largely owned by existing products. Residual hypotheses are owner-specific shadow dependency mapping and change-to-outcome evidence closure. A full 3-day probe is not justified. | Deferred 90-minute pre-gate only. Continue only if owner mapping adds meaningful edges with zero false-safe results and reproducible evidence. |
| BenchProof | USE EXISTING | Video-to-SOP, approved procedures, guided checklists, photo/video evidence, signatures, and audit history are existing-product territory. The residual passive continuous-video verification gap cannot currently justify critical-step false-safe = 0. | Re-open only with materially better calibrated procedural-video verification, strict human-correction persistence, or a real recurring task (about monthly or more) with clear failure cost. |
| RestoreProof | NEXT AUDIT | Not yet independently falsified against mature restore/verification products and realistic compositions. | Zero-base audit next. First challenge whether Kopia, restic, Veeam, and similar products already own restore + checksum + smoke-test + evidence workflows. |
| AgentProof | PROBE CANDIDATE | Pending independent audit. | Audit after higher-priority candidates unless new evidence changes priority. |
| Concept OS | PROBE CANDIDATE | Separate application hypothesis; not Foundation completion work. | Re-evaluate after higher-priority opportunity audits. |
| Ambient AI | WATCH | Separate application; currently deferred. | Re-open on a stronger concrete use case or meaningful external capability/cost change. |

## Decision rules

- Do not treat Foundation reuse as sufficient reason to build.
- Prefer mature products or realistic compositions when they cover the practical value.
- Distinguish a genuine residual gap from generic capabilities already owned by vendors or OSS.
- Use the smallest pre-gate necessary before committing multi-day implementation or probe time.
- A rejected or reduced candidate is re-opened only when its recorded condition changes or new evidence invalidates the prior decision.
- Do not copy large research reports into canonical Foundation documents; preserve the decision, rationale, re-open condition, and references where available.
- If a candidate becomes BUILD NOW and its boundary with Foundation is formally decided, record that architecture decision separately, for example as an ADR.

## Decision history

### 2026-09-29 — ChangeProof

Verdict: **REDUCE**

Independent re-audit found that five of ten functional stages are already owned by existing products, three mainly require composition, and only two remain genuine-gap candidates:

1. owner-specific shadow dependency mapping;
2. change-to-outcome evidence closure.

Notification ingestion, tenant/asset inventory, CVE mapping, configuration drift, approval, and reporting are not reasons to build ChangeProof.

Do not proceed directly to a three-day probe. The only retained experiment is a 90-minute, maximum four-hour owner-mapping pre-gate. The pre-gate itself does not justify integrating ChangeProof into Foundation.

### 2026-09-29 — BenchProof

Verdict: **USE EXISTING**

Existing products cover video-to-SOP generation, approved procedures, guided execution, required photo/video evidence, signatures, reference-image checks, and audit history.

The residual gap is passive continuous-video detection of undeclared skipped, wrong-order, or failed steps without requiring operator evidence submission. Current video-model evidence does not justify assuming zero false-safe results for critical steps. When verification is constrained to visual/state/external evidence contracts, the practical solution converges toward existing guided-evidence workflows.

No one-day probe or 90-minute video-model test is currently justified. Re-open only if one of the recorded conditions materially changes.

### 2026-09-29 — RestoreProof

Status: **NEXT AUDIT**

The next zero-base audit should test whether any independent value remains after accounting for mature restore and verification capabilities in Kopia, restic, Veeam, and realistic compositions. Do not assume that restore + checksum + smoke test + evidence history is a genuine gap until that audit is complete.
