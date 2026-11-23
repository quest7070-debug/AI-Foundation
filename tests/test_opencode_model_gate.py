"""Offline OpenCode model-level firewall and CLI acceptance without real AI."""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from ai_foundation.harness_public_canary import (
    PUBLIC_CANARY_PROMPT, PUBLIC_CANARY_SOURCE,
)
from ai_foundation.opencode_model_gate import (
    CONTAINER_MODEL, MODEL_ALIAS, SERVICE_ID, UPSTREAM_FREE_MODEL,
    ModelGateDenied, OfflineOpenCodeModelGate,
    opencode_v2_isolated_config, run_fixture_gate_for_test,
)
from ai_foundation.opencode_isolated_cli import (
    NativeIsolationReceipt, admission, safe_cli_plan, accept_public_cli_once,
)


def public_payload(**kw):
    return {"model": UPSTREAM_FREE_MODEL, "messages": [
        {"role": "user", "content": PUBLIC_CANARY_PROMPT}], **kw}


def post(port, body, *, route="/v1/chat/completions"):
    data = json.dumps(body).encode()
    request = Request(
        "http://127.0.0.1:" + str(port) + route,
        data=data, headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def synthetic_receipt(**updates):
    receipt = NativeIsolationReceipt(
        binary_sha256="a" * 64, verified_sha256="a" * 64,
        version="2.2.0",
        native_network_denies_all_external=True,
        only_loopback_gateway_allowed=True,
        filesystem_isolation_verified=True,
        shared_credentials_inaccessible=True,
        no_background_server_verified=True,
    )
    return replace(receipt, **updates)


def test_real_http_gate_denies_paid_private_tool_and_repeat_without_outbound():
    def exercise(port, gate):
        for content in (
            public_payload(model="gpt-6-astra"),
            public_payload(model="glm-5.3-flash"),
            public_payload(messages=[{"role":"user","content":"my private repo"}]),
            public_payload(tools=[{"type":"function"}]),
            public_payload(tool_choice="auto"),
            public_payload(messages=[{"role":"system","content":"hidden"},
                                    {"role":"user","content":PUBLIC_CANARY_PROMPT}]),
            public_payload(max_completion_tokens=10000),
        ):
            code, response = post(port, content)
            assert code == 403
            assert b"private repo" not in response and b"gpt-6-astra" not in response
        assert gate.accepted == 0 and gate.denied == 7
        ok, body = post(port, public_payload(stream=False, max_tokens=128))
        assert ok == 200
        assert json.loads(body)["choices"][0]["message"]["content"] == PUBLIC_CANARY_SOURCE
        assert gate.accepted == 1
        again, _ = post(port, public_payload())
        assert again == 403
        assert gate.accepted == 1 and gate.denied == 8
        assert len(gate.hashes) == 1 and len(gate.hashes[0]) == 64
        # No remote dispatch method exists.
        assert not hasattr(gate, "forward") and not hasattr(gate, "upstream")
    run_fixture_gate_for_test(exercise)


def test_gateway_rejects_hidden_nonpublic_paths_and_supports_offline_sse():
    def exercise(port, gate):
        status, data = post(port, public_payload(), route="/v1/responses")
        assert status == 404
        request = Request("http://127.0.0.1:" + str(port) + "/v1/models")
        with pytest.raises(HTTPError) as err:
            urlopen(request, timeout=3)
        assert err.value.code == 404
        status, data = post(port, public_payload(
            stream=True, stream_options={"include_usage": True}))
        assert status == 200 and b"data: [DONE]" in data
        assert PUBLIC_CANARY_SOURCE.encode().replace(b"\n", b"\\n") in data
        assert gate.accepted == 1
    run_fixture_gate_for_test(exercise)


def test_gateway_request_bounded_json_fields_and_clean_error_codes():
    gate = OfflineOpenCodeModelGate()
    for bad in (None, [], {}, public_payload(stream="yes"),
                public_payload(stream_options={"unexpected": True}),
                public_payload(temperature=100),
                public_payload(max_tokens=True)):
        with pytest.raises(ModelGateDenied):
            gate.accept(bad)
    assert gate.accepted == 0


def test_v2_cli_plan_only_has_single_local_provider_no_filesystem_tools():
    plan = safe_cli_plan(32147)
    assert plan["execution_authorized"] is False
    assert plan["mode"] == "HOST_OS_ISOLATION_REQUIRED"
    args = plan["argv"]
    assert args[1:3] == ["run", "--standalone"]
    assert "--pure" not in args
    assert "--auto" not in args and "--attach" not in args
    assert args[-1] == PUBLIC_CANARY_PROMPT
    assert args[args.index("--model") + 1] == CONTAINER_MODEL
    config = plan["config"]
    assert list(config["providers"]) == [SERVICE_ID]
    assert list(config["providers"][SERVICE_ID]["models"]) == [MODEL_ALIAS]
    assert MODEL_ALIAS == UPSTREAM_FREE_MODEL
    assert config["model"] == CONTAINER_MODEL
    assert config["providers"][SERVICE_ID]["models"][MODEL_ALIAS]["modelID"] == UPSTREAM_FREE_MODEL
    assert config["providers"][SERVICE_ID]["settings"]["baseURL"] == (
        "http://127.0.0.1:32147/v1")
    assert config["providers"][SERVICE_ID]["package"] == "@opencode/ai/providers/openai-compatible"
    assert config["permissions"] == [{"action": "*", "resource": "*", "effect": "deny"}]
    assert config["policies"] == [
        {"action": "provider.use", "resource": "*", "effect": "deny"},
        {"action": "provider.use", "resource": SERVICE_ID, "effect": "allow"},
    ]
    assert config["mcp"] == {} and config["plugins"] == []
    assert config["warming"] is False and config["compaction"]["auto"] is False
    assert not any(x in config for x in ("provider", "permission"))
    assert "apiKey" not in json.dumps(config)


def test_host_does_not_run_actual_subprocess_without_verified_os_sandbox():
    attempts = []
    def fake_runner(*args, **kwargs):
        attempts.append((args, kwargs))
        raise AssertionError("should not run")
    for receipt, reason in (
        (None, "HOST_OS_SANDBOX_NOT_ATTESTED"),
        (synthetic_receipt(native_network_denies_all_external=False),
         "EXTERNAL_EGRESS_NOT_BLOCKED"),
        (synthetic_receipt(filesystem_isolation_verified=False),
         "FILESYSTEM_SANDBOX_MISSING"),
        (synthetic_receipt(shared_credentials_inaccessible=False),
         "SHARED_SECRETS_ACCESSIBLE"),
        (synthetic_receipt(no_background_server_verified=False),
         "SHARED_SERVER_RISK"),
        (synthetic_receipt(version="1.0.0"), "OPENCODE_V2_BINARY_REQUIRED"),
        (synthetic_receipt(verified_sha256="b"*64),
         "BINARY_DIGEST_MISMATCH"),
    ):
        result = accept_public_cli_once(
            native_receipt=receipt, runner=fake_runner)
        assert result["status"] == reason and result["attempted"] is False
    assert attempts == []
    assert accept_public_cli_once(native_receipt=synthetic_receipt())[
        "status"] == "NATIVE_SANDBOX_RUNNER_REQUIRED"
    assert accept_public_cli_once(
        native_receipt=synthetic_receipt(), runner=subprocess.run)[
        "status"] == "NATIVE_SANDBOX_RUNNER_REQUIRED"


def test_offline_fake_cli_one_public_model_request_accepts_without_paid_calls():
    def sandbox_fake(argv, **kwargs):
        assert argv[1:2] == ["run"] and "--auto" not in argv
        assert argv[-1] == PUBLIC_CANARY_PROMPT
        assert kwargs["cwd"].startswith("/")
        env = kwargs["env"]
        assert env["OPENCODE_PURE"] == "1"
        assert env["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
        assert env["OPENCODE_DISABLE_EXTERNAL_SKILLS"] == "1"
        for secret_key in ("GROQ_API_KEY", "OPENAI_API_KEY", "OPENCODE_API_KEY",
                           "ANTHROPIC_API_KEY", "GITHUB_TOKEN"):
            assert secret_key not in env
        cfg = json.loads(env["OPENCODE_CONFIG_CONTENT"])
        assert list(cfg["providers"]) == [SERVICE_ID]
        address = cfg["providers"][SERVICE_ID]["settings"]["baseURL"]
        port = int(address.split(":")[-1].split("/")[0])
        code, raw = post(port, public_payload())
        assert code == 200
        source = json.loads(raw)["choices"][0]["message"]["content"]
        return SimpleNamespace(stdout=source.encode(), returncode=0)
    result = accept_public_cli_once(
        native_receipt=synthetic_receipt(), runner=sandbox_fake)
    assert result == {
        "status": "VERIFIED_OFFLINE_CLI_PUBLIC_FIXTURE",
        "attempted": True, "gateway_accepted": 1,
        "gateway_denied": 0, "outside_inference_calls": 0,
        "accepted": True,
    }


def test_fake_cli_extra_paid_model_request_or_tainted_output_cannot_pass():
    def fake_runner(argv, **kwargs):
        cfg = json.loads(kwargs["env"]["OPENCODE_CONFIG_CONTENT"])
        port = int(cfg["providers"][SERVICE_ID]["settings"]["baseURL"].split(":")[-1].split("/")[0])
        code, _ = post(port, public_payload(model="gpt-6-astra"))
        assert code == 403
        return SimpleNamespace(stdout=PUBLIC_CANARY_SOURCE.encode(),
                               returncode=0)
    r = accept_public_cli_once(native_receipt=synthetic_receipt(),
                               runner=fake_runner)
    assert r["accepted"] is False
    assert r["gateway_accepted"] == 0 and r["gateway_denied"] == 1
    assert r["outside_inference_calls"] == 0


def test_no_real_cli_or_provider_cost_is_claimed_by_fixture_testing():
    assert admission(synthetic_receipt()) == "HOST_OS_SANDBOX_ATTESTED"
    assert opencode_v2_isolated_config(12000)["model"] == CONTAINER_MODEL
    assert PUBLIC_CANARY_PROMPT.startswith("Public nonsecret smoke test")


def test_canary_agent_implements_existing_harness_proposal_port_with_zero_github_tools():
    from ai_foundation.agent import AgentRequest, AgentResult
    from ai_foundation.opencode_isolated_cli import OfflineOpenCodeCanaryAgent

    def sandbox_fake(argv, **kwargs):
        config = json.loads(kwargs["env"]["OPENCODE_CONFIG_CONTENT"])
        url = config["providers"][SERVICE_ID]["settings"]["baseURL"]
        port = int(url.rsplit(":", 1)[1].split("/")[0])
        status, response = post(port, public_payload())
        assert status == 200
        content = json.loads(response)["choices"][0]["message"]["content"]
        return SimpleNamespace(stdout=content.encode(), returncode=0)

    port = OfflineOpenCodeCanaryAgent(
        native_receipt=synthetic_receipt(), runner=sandbox_fake)
    result = port.run(AgentRequest(PUBLIC_CANARY_PROMPT))
    assert isinstance(result, AgentResult)
    assert result.output == PUBLIC_CANARY_SOURCE

    for invalid in (
        AgentRequest("inspect private project"),
        AgentRequest(PUBLIC_CANARY_PROMPT, message_history=("private",)),
    ):
        with pytest.raises(ValueError, match="OPENCODE_PUBLIC_FIXTURE_ONLY"):
            port.run(invalid)
    # The default real-process path is impossible without a trusted OS
    # sandbox launcher, even when the caller provides a synthetic receipt.
    with pytest.raises(RuntimeError, match="OPENCODE_CLI_NOT_ACCEPTED"):
        OfflineOpenCodeCanaryAgent(
            native_receipt=synthetic_receipt()).run(
                AgentRequest(PUBLIC_CANARY_PROMPT))


def test_paid_helper_after_valid_public_response_invalidates_entire_cli():
    """A successful main-model answer must not conceal paid background calls."""
    def fake_runner(argv, **kwargs):
        cfg = json.loads(kwargs["env"]["OPENCODE_CONFIG_CONTENT"])
        url = cfg["providers"][SERVICE_ID]["settings"]["baseURL"]
        port = int(url.rsplit(":", 1)[1].split("/")[0])
        assert post(port, public_payload())[0] == 200
        assert post(port, public_payload(model="gpt-6-astra"))[0] == 403
        return SimpleNamespace(stdout=PUBLIC_CANARY_SOURCE.encode(), returncode=0)

    verdict = accept_public_cli_once(native_receipt=synthetic_receipt(),
                                     runner=fake_runner)
    assert verdict["status"] == "OPENCODE_FIXTURE_NOT_ACCEPTED"
    assert verdict["accepted"] is False
    assert verdict["gateway_accepted"] == 1
    assert verdict["gateway_denied"] == 1


def test_hidden_model_probe_or_duplicate_key_invalidates_acceptance():
    """Denied auxiliary endpoints and ambiguous JSON must be counted."""
    def simulate(port, gate):
        assert post(port, public_payload())[0] == 200
        req = Request("http://127.0.0.1:" + str(port) + "/v1/models")
        with pytest.raises(HTTPError) as err:
            urlopen(req, timeout=3)
        assert err.value.code == 404
        raw = (b'{"model":"gpt-6-astra","model":"'
               + UPSTREAM_FREE_MODEL.encode()
               + b'","messages":[{"role":"user","content":'
               + json.dumps(PUBLIC_CANARY_PROMPT).encode() + b'}]}')
        req = Request("http://127.0.0.1:" + str(port) +
                      "/v1/chat/completions", data=raw, method="POST")
        with pytest.raises(HTTPError) as err2:
            urlopen(req, timeout=3)
        assert err2.value.code == 400
        assert gate.accepted == 1 and gate.denied == 2

    run_fixture_gate_for_test(simulate)


def test_cli_failure_code_never_exposes_untrusted_stderr():
    def failed_cli(argv, **kwargs):
        return SimpleNamespace(stdout=b"", returncode=2,
                               stderr=b"private-token-DO-NOT-LOG unknown option")
    report = accept_public_cli_once(
        native_receipt=synthetic_receipt(), runner=failed_cli)
    assert report["status"] == "OPENCODE_FIXTURE_NOT_ACCEPTED"
    assert report["accepted"] is False
    assert report["gateway_accepted"] == 0 and report["gateway_denied"] == 0
    assert report["cli_exit_code"] == 2
    assert report["cli_failure_class"] == "CLI_UNSUPPORTED_FLAG"
    assert "private-token" not in json.dumps(report)


def test_denied_request_shape_is_metadata_only_without_prompt_content():
    gate = OfflineOpenCodeModelGate()
    bad = public_payload(
        messages=[{"role": "system", "content": "private-secret-NEVER-EXPORT"},
                  {"role": "user", "content": PUBLIC_CANARY_PROMPT}],
        tools=[{"type": "function", "function": {"name": "private"}}])
    with pytest.raises(ModelGateDenied):
        gate.accept(bad)
    assert gate.accepted == 0 and gate.denied == 1
    assert len(gate.denied_shapes) == 1
    shape = gate.denied_shapes[0]
    assert shape["has_tools"] is True
    assert shape["message_count"] == 2
    assert shape["message_roles"] == ["system", "user"]
    assert shape["public_prompt_present"] is True
    assert shape["user_content_type"] == "STRING"
    assert "private" not in json.dumps(shape)


def test_acp_offline_gate_rejects_same_length_modified_system_and_extra_context():
    # Public prompt alone is insufficient: altered system, tool or context denied.
    gate = OfflineOpenCodeModelGate()
    acp = public_payload(
        messages=[{"role": "system", "content": "x" * 1439},
                  {"role": "user", "content": PUBLIC_CANARY_PROMPT}],
        tools=[{"type": "function", "function": {"name": "untrusted"}}])
    for changed in (
        acp,
        {**acp, "messages": acp["messages"] + [
            {"role": "user", "content": "private extra"}]},
        {**acp, "messages": [acp["messages"][0],
            {"role": "user", "content": PUBLIC_CANARY_PROMPT + " extra"}]},
    ):
        with pytest.raises(ModelGateDenied, match="GATE_NONPUBLIC_PROMPT_DENIED"):
            gate.accept(changed)
    assert gate.accepted == 0 and gate.denied == 3
