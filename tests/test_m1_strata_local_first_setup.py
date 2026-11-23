"""Focused one-shot setup checks; no local models or network required."""
import json
import os
from pathlib import Path
from scripts.m1_strata_local_first_setup import configure_strata


def test_setup_is_idempotent_and_preserves_existing_local_routes(tmp_path):
    parent = tmp_path / "local-compute"
    parent.mkdir(mode=0o700)
    original = {"name": "m1", "base_url": "http://127.0.0.1:11434"}
    target = parent / "endpoints.json"
    target.write_text(json.dumps({"version": 1, "endpoints": [original]}))
    target.chmod(0o600)
    assert configure_strata(tmp_path) == "READY_TO_APPLY"
    assert len(json.loads(target.read_text())["endpoints"]) == 1
    assert configure_strata(tmp_path, apply=True) in {"CONFIGURED", "CONFIGURED_KEY_REQUIRED"}
    rows = json.loads(target.read_text())["endpoints"]
    assert len(rows) == 2 and rows[0] == original
    assert rows[1]["api_key_env"] == "STRATA_API_KEY"
    assert rows[1]["base_url"] == "http://10.0.1.1:8080"
    assert configure_strata(tmp_path, apply=True) == "ALREADY_CONFIGURED"
    assert os.stat(target).st_mode & 0o077 == 0


def test_setup_refuses_to_overwrite_existing_strata(tmp_path):
    parent = tmp_path / "local-compute"
    parent.mkdir(mode=0o700)
    target = parent / "endpoints.json"
    previous = {"name": "mainpc-strata", "base_url": "http://10.0.1.1:18080"}
    target.write_text(json.dumps({"version": 1, "endpoints": [previous]}))
    target.chmod(0o600)
    assert configure_strata(tmp_path, apply=True) == "EXISTING_ENDPOINT_REVIEW_REQUIRED"
    assert json.loads(target.read_text())["endpoints"] == [previous]


def test_setup_can_repair_only_invalid_key_name_with_explicit_flag(tmp_path):
    template = json.loads((Path(__file__).parents[1] /
        "docs/configs/mainpc-strata-endpoints.example.json").read_text())
    template["endpoints"][0]["api_key_env"] = "GITHUB_TOKEN"
    parent = tmp_path / "local-compute"
    parent.mkdir(mode=0o700)
    target = parent / "endpoints.json"
    target.write_text(json.dumps(template))
    target.chmod(0o600)
    assert configure_strata(tmp_path, apply=True) == "EXISTING_ENDPOINT_REVIEW_REQUIRED"
    assert configure_strata(tmp_path, repair_invalid_key=True) == "READY_TO_REPAIR_KEY_BINDING"
    assert configure_strata(tmp_path, apply=True, repair_invalid_key=True) in {
        "KEY_BINDING_REPAIRED", "KEY_BINDING_REPAIRED_KEY_REQUIRED"}
    assert json.loads(target.read_text())["endpoints"][0]["api_key_env"] == "STRATA_API_KEY"
    template["endpoints"][0]["api_key_env"] = "MAINPC_STRATA_OWNER_TOKEN"
    target.write_text(json.dumps(template))
    target.chmod(0o600)
    assert configure_strata(tmp_path, apply=True, repair_invalid_key=True) == "EXISTING_ENDPOINT_REVIEW_REQUIRED"


def test_reviewed_retarget_only_changes_verified_strata_route(tmp_path):
    template = json.loads((Path(__file__).parents[1] /
        "docs/configs/mainpc-strata-endpoints.example.json").read_text())
    mainpc = template["endpoints"][0]
    mainpc["roles_note"] = "host-preserved"
    mainpc["models"][0]["roles"] = ["CODE", "DEVELOPMENT_AGENT"]
    mainpc["base_url"] = "http://100.80.11.110:8080"
    mainpc["allowed_hosts"] = ["100.80.11.110"]
    m1 = {"name":"m1","base_url":"http://127.0.0.1:11434"}
    parent = tmp_path / "local-compute"
    parent.mkdir(mode=0o700)
    target = parent / "endpoints.json"
    target.write_text(json.dumps({"version":1,"endpoints":[m1,mainpc]}))
    target.chmod(0o600)
    assert configure_strata(tmp_path,port=18080,apply=True) == "EXISTING_ENDPOINT_REVIEW_REQUIRED"
    assert configure_strata(tmp_path,port=18080,retarget_existing=True) == "READY_TO_RETARGET"
    assert configure_strata(tmp_path,port=18080,retarget_existing=True,apply=True) == "RETARGETED_TO_18080"
    rows = json.loads(target.read_text())["endpoints"]
    assert rows[0] == m1
    assert rows[1] == {**mainpc,"base_url":"http://10.0.1.1:18080",
                       "allowed_hosts":["10.0.1.1"]}
    assert configure_strata(tmp_path,port=18080,retarget_existing=True,apply=True) == "ALREADY_TARGETED"


def test_retarget_refuses_unknown_models_and_unreviewed_ports(tmp_path):
    template = json.loads((Path(__file__).parents[1] /
        "docs/configs/mainpc-strata-endpoints.example.json").read_text())
    template["endpoints"][0]["models"][0]["runtime_model"] = "wrong"
    parent = tmp_path / "local-compute"
    parent.mkdir(mode=0o700)
    path = parent / "endpoints.json"
    path.write_text(json.dumps(template))
    path.chmod(0o600)
    assert configure_strata(tmp_path,port=18080,retarget_existing=True,apply=True) == "EXISTING_ENDPOINT_REVIEW_REQUIRED"
    assert json.loads(path.read_text()) == template


def test_register_refuses_unauthenticated_server_without_prompt(tmp_path,monkeypatch):
    import io
    from urllib import request
    from scripts import m1_strata_local_first_setup as setup
    template = json.loads((Path(__file__).parents[1] /
        "docs/configs/mainpc-strata-endpoints.example.json").read_text())
    template["endpoints"][0]["base_url"] = "http://10.0.1.1:18080"
    parent = tmp_path / "local-compute"
    parent.mkdir(mode=0o700)
    path = parent / "endpoints.json"
    path.write_text(json.dumps(template))
    class Response:
        status = 200
        def __enter__(self):return self
        def __exit__(self,*a):return None
        def read(self,n):return b'{"api_key":false,"loaded":true}'
    class Opener:
        def open(self,*args,**kw):return Response()
    monkeypatch.setattr(request,"build_opener",lambda *a:Opener())
    called=[]
    assert setup.register_owner_key(tmp_path,secret_prompt=lambda *_:called.append(1)) == "STRATA_AUTH_NOT_READY"
    assert not called


def test_retarget_blocker_is_fixed_nonsecret_code_only():
    from scripts.m1_strata_local_first_setup import retarget_blocker
    example = json.loads((Path(__file__).parents[1] /
        "docs/configs/mainpc-strata-endpoints.example.json").read_text())["endpoints"][0]
    example["api_key_env"] = "STRATA_API_KEY"
    assert retarget_blocker(example) == "NO_POLICY_BLOCKER"
    example["base_url"] = "http://unexpected.host:8080"
    assert retarget_blocker(example) == "URL_POLICY"
    example["base_url"] = "http://10.0.1.1:18080"
    example["models"][0]["roles"] = ["CHAT"]
    assert retarget_blocker(example) == "CODE_MODEL_POLICY"


def test_older_owner_endpoint_is_idempotent_after_retarget(tmp_path):
    template = json.loads((Path(__file__).parents[1] /
        "docs/configs/mainpc-strata-endpoints.example.json").read_text())
    row = template["endpoints"][0]
    row["models"][0]["capabilities"] = ["CHAT", "CODE"]
    row["models"][0]["roles"] = ["CODE", "DEVELOPMENT_AGENT"]
    row["api_key_env"] = "STRATA_API_KEY"
    parent = tmp_path / "local-compute"
    parent.mkdir(mode=0o700)
    path = parent / "endpoints.json"
    path.write_text(json.dumps(template))
    path.chmod(0o600)
    assert configure_strata(tmp_path, port=18080,
                            retarget_existing=True, apply=True) == "RETARGETED_TO_18080"
    assert configure_strata(tmp_path, port=18080,
                            retarget_existing=True, apply=True) == "ALREADY_TARGETED"


def test_explicit_text_expansion_preserves_existing_endpoint_and_private_routes(tmp_path):
    template = json.loads((Path(__file__).parents[1] /
        "docs/configs/mainpc-strata-endpoints.example.json").read_text())
    old = template["endpoints"][0]
    old["base_url"] = "http://10.0.1.1:18080"
    old["models"][0]["capabilities"] = ["CODE"]
    old["models"][0]["roles"] = ["DEVELOPMENT_AGENT"]
    old["owner_metadata"] = "preserve"
    m1 = {"name": "m1", "base_url": "http://127.0.0.1:11434"}
    parent = tmp_path / "local-compute"
    parent.mkdir(mode=0o700)
    target = parent / "endpoints.json"
    target.write_text(json.dumps({"version": 1, "endpoints": [m1, old]}))
    target.chmod(0o600)
    before = target.read_bytes()
    assert configure_strata(tmp_path, port=18080, apply=True) == "EXISTING_ENDPOINT_REVIEW_REQUIRED"
    assert configure_strata(tmp_path, port=18080, expand_text_roles=True) == "READY_TO_EXPAND_TEXT"
    assert target.read_bytes() == before
    assert configure_strata(tmp_path, port=18080, expand_text_roles=True, apply=True) == "TEXT_ROLES_EXPANDED"
    rows = json.loads(target.read_text())["endpoints"]
    assert rows[0] == m1
    assert rows[1]["base_url"] == old["base_url"]
    assert rows[1]["owner_metadata"] == old["owner_metadata"]
    assert rows[1]["api_key_env"] == old["api_key_env"]
    assert rows[1]["models"][0]["capabilities"] == ["CODE", "CHAT"]
    assert "PUBLIC_TEXT_ANALYSIS" in rows[1]["models"][0]["roles"]
    assert os.stat(target).st_mode & 0o077 == 0
    assert configure_strata(tmp_path, port=18080, expand_text_roles=True, apply=True) == "ALREADY_TEXT_ENABLED"


def test_text_expansion_denies_unknown_model_and_unreviewed_capabilities(tmp_path):
    template = json.loads((Path(__file__).parents[1] /
        "docs/configs/mainpc-strata-endpoints.example.json").read_text())
    row = template["endpoints"][0]
    row["base_url"] = "http://10.0.1.1:18080"
    row["models"][0]["capabilities"] = ["CODE", "PC_CONTROL"]
    parent = tmp_path / "local-compute"
    parent.mkdir(mode=0o700)
    target = parent / "endpoints.json"
    target.write_text(json.dumps(template))
    target.chmod(0o600)
    initial = target.read_bytes()
    assert configure_strata(tmp_path, port=18080, expand_text_roles=True, apply=True) == "EXISTING_ENDPOINT_REVIEW_REQUIRED"
    assert target.read_bytes() == initial
    row["models"][0]["capabilities"] = ["CODE"]
    row["models"][0]["runtime_model"] = "spoof-model"
    target.write_text(json.dumps(template))
    initial = target.read_bytes()
    assert configure_strata(tmp_path, port=18080, expand_text_roles=True, apply=True) == "EXISTING_ENDPOINT_REVIEW_REQUIRED"
    assert target.read_bytes() == initial
