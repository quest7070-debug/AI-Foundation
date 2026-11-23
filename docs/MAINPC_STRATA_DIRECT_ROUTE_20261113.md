# MainPC Strata as a guarded Foundation development compute backend

Status: **source implementation, not M1/Windows installed acceptance** (2026-11-13).
This supplements the local-first MCP development work in PR #958; it does
not replace Foundation Host/Guard/Work/Harness, and it does not activate Kandev.

## Current source-evidenced topology

- M1 Mac: always-on Foundation Host, Guard, local acceptance, existing M1 9B
  insurance, secret/HumanModel owners, and optional existing WoL script.
- Windows MainPC: on-demand Strata OpenAI-compatible inference serving
  `qwen3.8-flash-next-coder-iq1_m` for CODE/development proposals.
- Physical direct-link historical addresses: M1 `10.0.1.2` and MainPC
  `10.0.1.1` over 1GbE.
- Preferred direct-link endpoint when Strata is LAN-bound:
  `http://10.0.1.1:8080`; older Windows localhost-only configurations
  used a fixed portproxy at `10.0.1.1:18080`. The operator must **observe**
  which is currently active, never assume either.
- Independent 2026-11-07 live acceptance used `100.80.11.110:8080`
  (Tailscale), with `STRATA_API_KEY` Bearer auth, a model discovery and an
  actual `ADAPTER-PASS` response. This is historical evidence, **not**
  evidence of present direct-LAN reachability.

## Exact host-owned connection

Copy `docs/configs/mainpc-strata-endpoints.example.json` to the installed
M1 **data-root** `local-compute/endpoints.json` using the existing guarded
configuration/change workflow. If the installed configuration already lists
other local endpoints, **append only the reviewed Strata entry**, retaining
those other endpoints. Never commit a real credential or overwrite existing
configuration just to enable Strata.

The example binds `local:mainpc-strata:code-agent` to one exact runtime model
and CODE role. The endpoint host is explicitly allowlisted and only the
`STRATA_API_KEY` **environment variable name** appears in the JSON.
The actual secret must come from the already trusted owner credential/launcher
environment. The example marks this endpoint `optional: true`, so a missing
owner environment variable leaves MainPC Strata disabled **without aborting**
Foundation startup or harming M1 routes. Required endpoints retain their
existing strict missing-key rejection. Do not fall back to unauthenticated
traffic, paid API, an arbitrary hostname, or a guessed model.

The existing `build_inference_composition` loads this file. Remote-local
OpenAI candidates are flagged `same_host=False`; `ComputeRouter` selects
**only same-host** models for LOCAL_ONLY data. For host-reviewed public work,
a healthy MainPC specialist is preferred as a local fallback after eligible
Free cloud routing; M1 remains the isolation/failure fallback.

For Harness-generated proposals (as opposed to ordinary CHAT), the trusted
caller must supply both the existing `local_registry` and the exact
`local_execution_by_prefix` derived from the same approved endpoint loading:

```python
entries = load_local_endpoints(data_root / "local-compute" / "endpoints.json")
# Use the same endpoint registry in the canonical host composition.
bound = tuple((prefix, execution) for prefix, _, execution in entries)
run_harness_managed_development_task(
    ...,
    local_execution_by_prefix=bound,  # trusted host only, NOT MCP JSON
)
```

The existing Harness-admitted public source review / Free-only policy,
Guard, isolated checkout, independent tests, one-shot Work claim and Git
Draft delivery boundaries remain. The previously incorrect adapter behavior
that sent all LOCAL routes to M1 regardless of the selected binding is fixed.
Strata is not a generic MCP shell, authority-granting agent or new scheduler.

## One-shot M1 probe / explicit wake

From the installed Foundation repository, after the owner key has been loaded
into the trusted environment:

```bash
python3 scripts/mainpc_strata_preflight.py --config "$FOUNDATION_DATA_ROOT/local-compute/endpoints.json"
python3 scripts/mainpc_strata_preflight.py --config "$FOUNDATION_DATA_ROOT/local-compute/endpoints.json" --smoke
python3 scripts/mainpc_strata_preflight.py --config "$FOUNDATION_DATA_ROOT/local-compute/endpoints.json" --wake --smoke
```

The default does not wake the PC or send a model prompt. `--smoke` sends only
a fixed synthetic string and requires exactly `STRATA_ROUTE_OK` to claim
`INFERENCE_VERIFIED`. `--wake` only uses the already-owned
`~/wake-desktop.py` once after discovery fails, waits at most 60 seconds,
and never powers off, changes Windows services, installs Strata, exposes a
public port, or resets a running model. Unsafe/absent WoL script returns
`WAKE_UNAVAILABLE`. No raw provider body, URL with query, prompt, model
output, environment token, stderr or private file path appears in the receipt.

If the existing Windows Strata process is localhost-only, the owner must
verify its existing fixed portproxy or LAN listening mode, Windows Firewall,
API key and sleep behavior on the actual machine. Do not enable a new broad
listener or auto-start service without inspecting installed settings.

## Real acceptance not yet met

1. Observed M1→MainPC direct-LAN `/v1/models` with exact runtime model and
   authorized Bearer key, then synthetic `INFERENCE_VERIFIED`.
2. One real Host/Guard/Harness public-code task returns
   `local:mainpc-strata:code-agent` and independently passes M1 local tests.
   A private HumanModel / secret-bearing task must use same-host M1 only.
3. The same receipt is visible in Operator and returned to the external AI's
   authenticated MCP caller, then a deliberate GitHub Draft/CI delivery.
4. Independently verify the installed runtime revision; PR/CI success alone
   is not MainPC activation or ChatGPT/Muse connectivity.

No local9B restart, paid API, Kandev, old193 signal, main merge or production
cutover is part of this source change.
