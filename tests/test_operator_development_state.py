"""Current, read-only development projections do not claim installed services."""
from ai_foundation.guard import GuardCore
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.operator_server import OperatorApplication
from ai_foundation.productization import FoundationConfig
from ai_foundation.store import SQLiteGuardStore


def test_host_status_inflight_never_blocks_operator_http_or_repeats_probe():
    from threading import Event, Thread
    from time import monotonic
    from ai_foundation.operator_server import cached_owner_development_status

    started, release = Event(), Event()
    calls = []
    def slow_host_readback():
        calls.append("start")
        started.set()
        assert release.wait(3)
        return {"state": "SCHEDULED_IDLE", "queue_state": "NO_QUEUED_TASK"}

    observe = cached_owner_development_status(slow_host_readback)
    first = []
    worker = Thread(target=lambda: first.append(observe()), daemon=True)
    worker.start()
    try:
        assert started.wait(2)
        begin = monotonic()
        assert observe() == {"state": "UNAVAILABLE", "queue_state": "UNAVAILABLE"}
        assert monotonic() - begin < 1
        assert calls == ["start"]
    finally:
        release.set()
        worker.join(timeout=3)
    assert not worker.is_alive()
    assert first == [{"state": "SCHEDULED_IDLE", "queue_state": "NO_QUEUED_TASK"}]
    assert observe() == first[0]
    assert calls == ["start"]


def test_operator_development_settings_share_current_guard_and_work(tmp_path):
    root = tmp_path / "foundation"
    root.mkdir()
    config = FoundationConfig(str(root.resolve()))
    store = SQLiteGuardStore(root / config.guard_db)
    guard = GuardCore(store.load(), store=store)
    app = OperatorApplication(config, OperatorActions(guard))
    initial = app.human_payload()["development"]
    assert initial["source"] == "CURRENT_GUARD_WORK_SNAPSHOT"
    assert initial["guard_pending"] == 0
    assert initial["approved_humanmodel_view"] == "UNVERIFIED"
    assert initial["local9b_worker"] == "UNVERIFIED"
    assert initial["eligible_recipes"] is None

    store.request_approval("bound-1", "production_deploy", "private-target",
                           "canon-1", "effect-1")
    store.request_approval("legacy-1", "send_email", "unbound-recipient")
    observed = app.human_payload()["development"]
    assert observed["guard_pending"] == 2
    assert observed["guard_actionable"] == 1
    assert observed["guard_unbound"] == 1
    assert observed["work_running"] == 0
    assert observed["work_waiting_human"] == 0
    assert "private-target" not in str(observed)
    assert "unbound-recipient" not in str(observed)

    html = app.page()
    assert "DEVELOPMENT / APPROVAL" in html
    assert "EXACT PENDING / 1" in html
    assert "UNBOUND / 1" in html
    assert "LOCAL 9B WORKER / UNVERIFIED" in html
    assert "APPROVED HUMANMODEL VIEW / UNVERIFIED" in html
    assert "private-target" not in html
    assert "unbound-recipient" not in html
    ref = next(n for n in app.human_payload()["notices"]
               if n["subject"] == "bound-1")["approval_ref"]
    assert app.act("approve", "bound-1", ref).ok
    latest = app.human_payload()["development"]
    assert latest["guard_pending"] == 1
    assert latest["guard_actionable"] == 0
    assert latest["guard_unbound"] == 1


def test_operator_displays_owner_observed_local9b_queue_without_private_fields(tmp_path):
    root = tmp_path / "foundation"
    root.mkdir()
    config = FoundationConfig(str(root.resolve()))
    guard_store = SQLiteGuardStore(root / config.guard_db)
    guard = GuardCore(guard_store.load(), store=guard_store)
    def owner_readback():
        return {
            "state": "SCHEDULED_IDLE", "queue_state": "QUEUED_NOT_RUNNING",
            "intake": {"queued_count": 2, "source": "SECRET_PRIVATE_SOURCE"},
            "last_failure": {"error_code": "REMOTE_PUSH_UNCERTAIN",
                             "detail": "SECRET_PRIVATE_PATH"},
            "private": "SECRET_USER_RECORD",
            "klm": {"status": "NOT_DUE", "fresh": True, "source": "SECRET_OWNER_PATH"},
        }
    app = OperatorApplication(config, OperatorActions(guard),
                              development_status=owner_readback)
    observed = app.human_payload()["development"]
    assert observed["source"] == "CURRENT_GUARD_WORK_SNAPSHOT+M1_OWNER_RUNTIME"
    assert observed["local9b_worker"] == "SCHEDULED_IDLE"
    assert observed["local9b_queue_state"] == "QUEUED_NOT_RUNNING"
    assert observed["local9b_queued_count"] == 2
    assert observed["local9b_last_failure_code"] == "REMOTE_PUSH_UNCERTAIN"
    assert observed["klm_status"] == "NOT_DUE"
    assert "SECRET_" not in str(observed)
    html = app.page()
    assert "LOCAL 9B QUEUE / QUEUED_NOT_RUNNING" in html
    assert "QUEUED / 2" in html
    assert "REMOTE_PUSH_UNCERTAIN" in html
    assert "KLM / OWNER SOURCE" in html and "NOT_DUE" in html
    assert "SECRET_" not in html


def test_operator_does_not_infer_worker_health_from_bad_or_missing_host_readback(tmp_path):
    root = tmp_path / "foundation"
    root.mkdir()
    config = FoundationConfig(str(root.resolve()))
    guard_store = SQLiteGuardStore(root / config.guard_db)
    actions = OperatorActions(GuardCore(guard_store.load(), store=guard_store))
    def unavailable():
        raise OSError("SECRET_HOST_PATH")
    for reader in (unavailable, lambda: {"state": "RUNNING",
                   "queue_state": "SECRET_UNTRUSTED_STATE",
                   "last_failure": {"error_code": "SECRET_TEXT"}}, None):
        app = OperatorApplication(config, actions, development_status=reader)
        projection = app.human_payload()["development"]
        assert projection["source"] == "CURRENT_GUARD_WORK_SNAPSHOT"
        assert projection["local9b_worker"] == "UNVERIFIED"
        assert projection["local9b_queue_state"] == "UNAVAILABLE"
        assert projection["local9b_queued_count"] is None
        assert "SECRET_" not in str(projection)



def test_operator_klm_report_requires_fresh_allowlisted_status(tmp_path):
    root = tmp_path / "foundation"
    root.mkdir()
    config = FoundationConfig(str(root.resolve()))
    store = SQLiteGuardStore(root / config.guard_db)
    actions = OperatorActions(GuardCore(store.load(), store=store))
    for invalid in ({"status": "CURRENT", "fresh": False},
                    {"status": "SECRET_PRIVATE_OWNER", "fresh": True},
                    {"status": "CURRENT", "fresh": 1}):
        app = OperatorApplication(config, actions, development_status=lambda: {
            "state": "SCHEDULED_IDLE", "queue_state": "NO_QUEUED_TASK",
            "klm": invalid,
        })
        result = app.human_payload()["development"]
        assert result["klm_status"] == "UNVERIFIED"
        assert "SECRET_" not in str(result)
    app = OperatorApplication(config, actions, development_status=lambda: {
        "state": "UNAVAILABLE", "queue_state": "UNAVAILABLE",
        "klm": {"status": "POLL_FAILED", "fresh": True},
    })
    observed = app.human_payload()["development"]
    assert observed["klm_status"] == "POLL_FAILED"
    assert observed["local9b_worker"] == "UNVERIFIED"
    app = OperatorApplication(config, actions, development_status=lambda: {
        "state": "UNAVAILABLE", "queue_state": "UNAVAILABLE",
        "humanmodel": {"view": "AVAILABLE"},
    })
    assert app.human_payload()["development"]["approved_humanmodel_view"] == "AVAILABLE"
    app = OperatorApplication(config, actions, development_status=lambda: {
        "state": "UNAVAILABLE", "queue_state": "UNAVAILABLE",
        "humanmodel": {"view": "SECRET_PRIVATE_OWNER"},
    })
    assert app.human_payload()["development"]["approved_humanmodel_view"] == "UNVERIFIED"



def test_operator_service_probes_reuse_one_observation_during_refresh(tmp_path):
    root = tmp_path / "foundation"
    root.mkdir()
    config = FoundationConfig(str(root.resolve()))
    store = SQLiteGuardStore(root / config.guard_db)
    guard = GuardCore(store.load(), store=store)
    calls = {"healthy": 0, "failed": 0}
    def healthy():
        calls["healthy"] += 1
        return True
    def failed():
        calls["failed"] += 1
        raise RuntimeError("SYNTHETIC_PRIVATE_HOST_ERROR")
    app = OperatorApplication(
        config, OperatorActions(guard),
        service_probes={"TOOLHIVE FILES": healthy, "TOOLHIVE CODE": failed})
    for _ in range(3):
        status = app.human_payload()
        assert status["services"] == [
            {"name": "TOOLHIVE FILES", "ok": True, "detail": "ready"},
            {"name": "TOOLHIVE CODE", "ok": None, "detail": "probe-failed"},
        ]
        assert "SYNTHETIC_PRIVATE" not in str(status)
    assert calls == {"healthy": 1, "failed": 1}


def test_direct_mcp_work_receipts_show_without_claiming_client_connection(tmp_path):
    root=tmp_path/"foundation"
    root.mkdir()
    config=FoundationConfig(str(root.resolve()))
    store=SQLiteGuardStore(root/config.guard_db)
    guard=GuardCore(store.load(),store=store)
    app=OperatorApplication(config,OperatorActions(guard),development_status=lambda: {
        "state":"UNAVAILABLE","queue_state":"UNAVAILABLE",
        "direct_mcp":{"state":"WORK_RECEIPTS_ONLY","running":1,
                      "verified_receipts":2,"failed":1,
                      "last_route":"STRATA","updated_at":1000,
                      "private_path":"SYNTHETIC_PRIVATE_SOURCE"}})
    observed=app.human_payload()["development"]
    assert observed["direct_mcp_status"]=="WORK_RECEIPTS_ONLY"
    assert observed["direct_mcp_verified_receipts"]==2
    assert observed["direct_mcp_last_route"]=="STRATA"
    assert observed["local9b_worker"]=="UNVERIFIED"
    page=app.page()
    assert "MCP / LOCAL CODE" in page and "LAST MODEL / STRATA" in page
    assert "MCP / CALLER PATH" in page and "UNVERIFIED" in page
    assert "SYNTHETIC_PRIVATE_SOURCE" not in page


def test_operator_klm_current_report_shows_rescan_without_false_current(tmp_path):
    root = tmp_path / "foundation"
    root.mkdir()
    cfg = FoundationConfig(str(root.resolve()))
    store = SQLiteGuardStore(root / cfg.guard_db)
    actions = OperatorActions(GuardCore(store.load(), store=store))
    sample = {
        "state": "SCHEDULED_IDLE", "queue_state": "NO_QUEUED_TASK",
        "klm": {"status": "RESCAN_REQUIRED", "fresh": True,
                "coverage": "COMPLETE", "changes": "RESCAN_REQUIRED",
                "folders": 34, "objects": 124, "pages": 34,
                "owner_root": "PRIVATE_CANARY_PATH"},
    }
    app = OperatorApplication(cfg, actions, development_status=lambda: sample)
    result = app.human_payload()["development"]
    assert result["klm_status"] == "RESCAN_REQUIRED"
    assert result["klm_coverage"] == "COMPLETE"
    assert result["klm_changes"] == "RESCAN_REQUIRED"
    assert (result["klm_folders"], result["klm_objects"], result["klm_pages"]) == (34, 124, 34)
    page = app.page()
    assert "RESCAN REQUIRED" in page
    assert "COVERAGE COMPLETE" in page and "CHANGES RESCAN_REQUIRED" in page
    assert "FOLDERS 34" in page and "OBJECTS 124" in page
    assert "PRIVATE_CANARY_PATH" not in page
    assert "CURRENT REPORT" not in page


def test_operator_klm_report_never_trusts_stale_or_malformed_counts(tmp_path):
    root = tmp_path / "foundation"
    root.mkdir()
    cfg = FoundationConfig(str(root.resolve()))
    store = SQLiteGuardStore(root / cfg.guard_db)
    actions = OperatorActions(GuardCore(store.load(), store=store))
    for fresh in (False, 1):
        app = OperatorApplication(cfg, actions, development_status=lambda: {
            "state": "SCHEDULED_IDLE", "queue_state": "NO_QUEUED_TASK",
            "klm": {"status": "CURRENT", "fresh": fresh, "coverage": "COMPLETE",
                    "changes": "COMPLETE", "folders": 34, "objects": 124}})
        state = app.human_payload()["development"]
        assert state["klm_status"] == "UNVERIFIED"
        assert state["klm_folders"] is None and state["klm_coverage"] == "UNVERIFIED"
    app = OperatorApplication(cfg, actions, development_status=lambda: {
        "state": "SCHEDULED_IDLE", "queue_state": "NO_QUEUED_TASK",
        "klm": {"status": "POLL_FAILED", "fresh": True,
                "coverage": "SECRET_UNKNOWN", "changes": "SECRET_PRIVATE",
                "folders": True, "objects": 100001, "pages": -1}})
    state = app.human_payload()["development"]
    assert state["klm_status"] == "POLL_FAILED"
    assert state["klm_coverage"] == "UNVERIFIED"
    assert state["klm_changes"] == "UNVERIFIED"
    assert all(state["klm_"+x] is None for x in ("folders", "objects", "pages"))
    assert "SECRET_" not in str(state)
    assert "SECRET_" not in app.page()


def test_operator_only_projects_fixed_consistent_local_review_triage(tmp_path):
    root = tmp_path / "foundation"
    root.mkdir()
    cfg = FoundationConfig(str(root.resolve()))
    store = SQLiteGuardStore(root / cfg.guard_db)
    app = OperatorApplication(cfg, OperatorActions(GuardCore(store.load(), store=store)))
    base = {"state": "OBSERVED", "atoms": 46, "missing_features": 8,
            "unresolved_reviews": 2, "relations": 0, "failed_intake": 1}
    valid = {"conflict": 1, "revision": 0, "qualifier": 0,
             "dependency": 1, "difference": 0, "duplicate": 0, "other": 0}
    app.klm_lifecycle_status = lambda: {**base, "review_triage": valid}
    dev = app.human_payload()["development"]
    assert dev["klm_review_triage"] == valid
    assert "REVIEW TRIAGE POTENTIAL CONFLICT 1" in app.page()
    # A caller-origin or malformed bucket may not become a source of HTML.
    app.klm_lifecycle_status = lambda: {
        **base, "review_triage": {**valid, "PRIVATE_OWNER_SECRET": 99}}
    dev = app.human_payload()["development"]
    assert dev.get("klm_review_triage") is None
    assert "PRIVATE_OWNER_SECRET" not in str(dev) + app.page()
    app.klm_lifecycle_status = lambda: {**base, "review_triage": {
        **valid, "conflict": 2}}
    assert app.human_payload()["development"].get("klm_review_triage") is None


def test_klm_lifecycle_reaches_api_and_overview_without_host_worker_callback(tmp_path):
    from ai_foundation.knowledge_lifecycle import ReadonlyReceiptJournal
    root = tmp_path / 'foundation'
    root.mkdir()
    cfg = FoundationConfig(str(root.resolve()))
    store = SQLiteGuardStore(root / cfg.guard_db)
    app = OperatorApplication(cfg, OperatorActions(GuardCore(store.load(), store=store)))
    ReadonlyReceiptJournal(root / cfg.work_db)
    observed = app.human_payload()['development']
    assert observed['klm_lifecycle_state'] == 'UNVERIFIED'
    assert observed['klm_atoms'] is None
    app.klm_lifecycle_status = lambda: {
        'state': 'OBSERVED', 'atoms': 45, 'missing_features': 8,
        'unresolved_reviews': 86, 'relations': 0, 'failed_intake': 1,
        'private': 'PRIVATE_CANARY',
    }
    observed = app.human_payload()['development']
    assert observed['klm_atoms'] == 45
    assert observed['klm_unresolved_reviews'] == 86
    page = app.page()
    assert 'KLM / PROCESSING' in page and 'REVIEW REQUIRED' in page
    assert 'UNRESOLVED REVIEWS 86' in page
    assert 'PRIVATE_CANARY' not in str(observed) + page



def test_owner_review_entry_visible_only_in_responsive_operator(tmp_path):
    root = tmp_path / "foundation"
    root.mkdir()
    config = FoundationConfig(str(root.resolve()))
    store = SQLiteGuardStore(root / config.guard_db)
    app = OperatorApplication(config, OperatorActions(GuardCore(store.load(), store=store)),
                              development_review=object())
    desktop = app.page("responsive")
    echo = app.page("echo")
    # Unified owner notification actions only; no secondary CODE review link.
    assert 'href="/development/review"' not in desktop
    assert 'id="development"' in desktop
    assert 'href="/development/review"' not in echo
    assert desktop.endswith("</body></html>")


def test_operator_displays_probe_observed_eligible_recipes(tmp_path):
    root = tmp_path / "foundation"
    root.mkdir()
    config = FoundationConfig(str(root.resolve()))
    guard_store = SQLiteGuardStore(root / config.guard_db)
    guard = GuardCore(guard_store.load(), store=guard_store)

    def owner_readback():
        return {
            "state": "SCHEDULED_IDLE", "queue_state": "NO_QUEUED_TASK",
            "intake": {"queued_count": 0},
            "recipes": {"eligible": 1, "source": "SECRET_PRIVATE_SOURCE"},
        }

    app = OperatorApplication(config, OperatorActions(guard),
                              development_status=owner_readback)
    observed = app.human_payload()["development"]
    assert observed["eligible_recipes"] == 1
    assert "SECRET_" not in str(observed)
    assert "ELIGIBLE RECIPES / 1" in app.page()


def test_operator_recipes_stay_unverified_when_malformed(tmp_path):
    root = tmp_path / "foundation"
    root.mkdir()
    config = FoundationConfig(str(root.resolve()))
    guard_store = SQLiteGuardStore(root / config.guard_db)
    guard = GuardCore(guard_store.load(), store=guard_store)
    for bad in ({"eligible": "1"}, {"eligible": 99}, {"eligible": True},
                {"other": 1}):
        app = OperatorApplication(
            config, OperatorActions(guard),
            development_status=lambda bad=bad: {"recipes": bad})
        assert app.human_payload()["development"]["eligible_recipes"] is None
