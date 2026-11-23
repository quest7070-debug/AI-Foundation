"""No-model contract: Codex GitHub CLI is a replaceable local 9B Harness front end."""
import pytest

from ai_foundation.agent import AgentRequest
from ai_foundation.codex_oss9b_port import MODEL, OLLAMA_HOST, host_bound_codex_oss9b
from ai_foundation.development_harness_roles import HarnessRoleRuntime


def binding():
    return host_bound_codex_oss9b(
        codex_binary="/opt/homebrew/bin/codex",
        seatbelt_profile="/private/foundation/guard.sb",
        private_home="/private/foundation/codex-oss9b",
        workdir="/private/foundation/public-work",
        timeout_s=120,
    )


def test_local_codex9b_reuses_existing_harness_role_boundary_no_cloud():
    port=binding()
    argv=port.argv_prefix
    assert argv[:4]==("/usr/bin/sandbox-exec","-f",
                      "/private/foundation/guard.sb","/opt/homebrew/bin/codex")
    assert argv[4:]==("exec","--ephemeral","--oss","--local-provider","ollama","--model","qwen3.5:9b",
                      "--sandbox","read-only","--skip-git-repo-check")
    assert MODEL == "qwen3.5:9b"
    assert OLLAMA_HOST == "127.0.0.1:11434"
    assert port.env["CODEX_HOME"]==port.env["HOME"]
    assert port.env["GIT_TERMINAL_PROMPT"]=="0"
    assert all(not name.startswith(("OPENAI_","CODEX_API_","ANTHROPIC_","GROQ_"))
               for name in port.env)
    assert "11436" not in str(port.argv_prefix) + str(port.env)
    assert "4b" not in str(port.argv_prefix)


def test_port_uses_existing_role_invocation_without_agent_execution(monkeypatch):
    calls=[]
    def fake_run(args, **kwargs):
        calls.append((args,kwargs["env"],kwargs["cwd"],kwargs["timeout"]))
        kwargs["stdout"].write(b'{"status":"ready"}')
        kwargs["stderr"].write(b"")
        return type("Result",(),{"returncode":0})()
    monkeypatch.setattr("ai_foundation.development_harness_roles.subprocess.run",fake_run)
    roles=HarnessRoleRuntime({"triage":binding()})
    assert roles.invoke("triage","public task only")=='{"status":"ready"}'
    assert calls[0][0][-1]=="public task only"
    assert calls[0][2]=="/private/foundation/public-work"
    assert calls[0][3]==120


@pytest.mark.parametrize("kwargs",[
    {"codex_binary":"codex"},
    {"seatbelt_profile":"/private/../tmp/guard.sb"},
    {"private_home":"/tmp"},
    {"private_home":"/"},
    {"workdir":"/private/work//bad"},
    {"timeout_s":0},
    {"timeout_s":True},
])
def test_unreviewed_paths_and_timeouts_fail_before_any_execution(kwargs):
    values=dict(codex_binary="/opt/homebrew/bin/codex",
                seatbelt_profile="/private/foundation/guard.sb",
                private_home="/private/foundation/codex-oss9b",
                workdir="/private/foundation/public-work",
                timeout_s=120)
    values.update(kwargs)
    with pytest.raises(ValueError,match="CODEX_OSS_"):
        host_bound_codex_oss9b(**values)
