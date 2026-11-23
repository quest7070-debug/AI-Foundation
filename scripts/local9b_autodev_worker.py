#!/usr/bin/env python3
"""Owned local 9B queue worker. Host-approved finite tasks only; no main merge."""
import os, sys, json, time, subprocess, tempfile, socket, re, errno, hashlib
from pathlib import Path
from urllib import request

ROOT=Path(__file__).resolve().parent
# The installed worker queue is durable and independent of any release path.
_STATE=os.environ.get("AI_FOUNDATION_LOCAL9B_STATE_ROOT")
STATE_ROOT=Path(_STATE).resolve(strict=True) if _STATE else ROOT
if _STATE and (not Path(_STATE).is_absolute() or Path(_STATE).is_symlink()
               or not STATE_ROOT.is_dir()
               or any(not (STATE_ROOT/d).is_dir() for d in ("inbox","results"))):
    raise RuntimeError("LOCAL9B_STATE_ROOT_UNVERIFIED")
HARNESS=Path("/Volumes/StorageVolume/home-data/deepseek-harness-standalone/handoff/harness9b-contract-20261106")
sys.path.insert(0,str(HARNESS/"experiments/harness9b"))
sys.path.insert(0,str(ROOT/"modules"))
# Use current-main code while preserving owner-pinned external Native modules.
sys.path.insert(0,str(ROOT.parent/"src"))
sys.path.insert(0,str(ROOT.parent))
from ai_foundation.development_host import HarnessProposalAgent,run_local_development_task
from ai_foundation.development_harness_roles import (HarnessRoleRuntime, HostBoundHarnessAgent, HarnessReviewGate)
from ai_foundation.host_compute_lease import HostComputeLease,HostComputeBusy
from ai_foundation.guard import GuardCore
from ai_foundation.core import GuardState
from native_code_compare import published_candidate,no_cloud_env,pinned_file,NATIVE_SEATBELT_NAME,NATIVE_SEATBELT_SHA
from native_fake_e2e import V6_PATCH_NAME,V6_PATCH_SHA256
PRIVATE=HARNESS/"private-dsh-home-stage-20261106"
OP=request.build_opener(request.ProxyHandler({}))
def api(port,path):
    with OP.open("http://127.0.0.1:"+str(port)+"/api/"+path,timeout=3) as r:return json.load(r)
def git(repo,*args):
    return subprocess.check_output(["git",*args],cwd=repo,text=True,timeout=60).strip()

def ensure_backend_port_available(port=11436):
    # This is a pre-model defer, not a consumed 9B attempt. An occupied local
    # backend must never use up the single-shot approved Issue claim.
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1",port))
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                raise HostComputeBusy("LOCAL_BACKEND_PORT_OCCUPIED") from exc
            raise

def optional_harness_role_patch(role):
    """Only owner-staged content-pinned local Harness role overlays are used."""
    if role not in ("REPAIR", "REVIEW"):
        raise ValueError("UNKNOWN_HARNESS_ROLE")
    path_text=os.environ.get("FOUNDATION_HARNESS_"+role+"_PATCH","")
    digest=os.environ.get("FOUNDATION_HARNESS_"+role+"_SHA256","")
    if not path_text and not digest:
        return None
    if not path_text or re.fullmatch(r"[a-f0-9]{64}",digest) is None:
        raise ValueError("HARNESS_ROLE_PROFILE_INCOMPLETE")
    path=Path(path_text)
    if path.is_symlink() or not path.is_file():
        raise ValueError("HARNESS_ROLE_PROFILE_INVALID")
    path=path.resolve(strict=True)
    path.relative_to(PRIVATE.resolve(strict=True))
    if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
        raise ValueError("HARNESS_ROLE_PROFILE_DRIFT")
    return path

def write_result(path,result):
    """Atomically persist an owner-only worker receipt without a public .tmp window.

    Intake/terminal results contain model diagnostics or owner-private paths.
    A fixed filename followed by chmod is vulnerable to collisions and may be
    readable before the chmod under a permissive umask. mkstemp creates an
    unpredictable 0600 inode in the existing owner-controlled result folder.
    """
    path=Path(path)
    if path.parent.is_symlink() or not path.parent.is_dir() or path.is_symlink():
        raise ValueError("UNTRUSTED_RESULT_PATH")
    fd,tmp=tempfile.mkstemp(prefix="."+path.name+".",suffix=".tmp",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            os.fchmod(out.fileno(),0o600)
            out.write(json.dumps(result,indent=2))
            out.flush()
            os.fsync(out.fileno())
        if path.is_symlink():
            raise ValueError("UNTRUSTED_RESULT_PATH")
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
def public_result_status(result):
    """Workflow-safe summary. The full receipt stays in owner-private storage."""
    status=result.get("status") if type(result) is dict else None
    if type(status) is not str or re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}",status) is None:
        status="UNVERIFIED"
    return {"status":status,"private_receipt_saved":True}

def _public_strata_endpoint(task):
    """No wake, no model dispatch: only exact reviewed-public CODE may offload."""
    if task.get("recipe")!="python-fixed-test" or task.get("model","m1")!="auto":
        return None
    # issue_task/resolve_task own authority; revalidate only the pinned recipe.
    from local9b_task_recipe import validate_contract
    validate_contract({k:v for k,v in task.items()
                       if k not in ("id","field","source_issue","source_digest")})
    root=os.environ.get("FOUNDATION_DATA_ROOT")
    if not root:
        # Existing owner worker LaunchAgent is not required to export the
        # Operator's data root. Reuse its exact validated installed --config
        # binding, never an inferred ~/data path or untrusted Issue field.
        try:
            from m1_human_model_activation_readiness import installed_paths
            installed=installed_paths()
            root=installed[1] if installed is not None else None
        except (OSError,ValueError,TypeError,KeyError):
            return None
    if (root is None or not Path(root).is_absolute()
            or Path(root).is_symlink() or not Path(root).is_dir()):
        return None
    from ai_foundation.local_endpoint_config import load_local_endpoints
    try:
        endpoints=load_local_endpoints(Path(root)/"local-compute"/"endpoints.json")
    except (OSError,ValueError,TypeError,KeyError):
        return None
    for prefix,discovery,execution in endpoints:
        if (prefix!="local:mainpc-strata"
                or getattr(execution,"models",{}).get("code-agent")!="qwen3.8-flash-next-coder-iq1_m"
                or not getattr(execution,"api_key",None)):
            continue
        try:
            if any(c.binding=="local:mainpc-strata:code-agent"
                   and c.health=="ONLINE" and "CODE" in c.capabilities
                   and getattr(c,"same_host",True) is False
                   for c in discovery.candidates()):
                return execution
        except (OSError,ValueError,TypeError,KeyError):
            pass
    return None


def _try_public_strata_task(task):
    """Use already-approved Strata first; None means safe *pre-dispatch* fallback.

    Once a remote prompt has been dispatched, keep its own terminal receipt.
    Never rerun the same changed source/PR on 9B after an uncertain response.
    """
    execution=_public_strata_endpoint(task)
    if execution is None:
        return None
    from ai_foundation.sensitive_input_scan import contains_sensitive_value
    from ai_foundation.harness_provider_adapter import compiled_source
    from ai_foundation.agent import AgentResult
    from local9b_task_recipe import FixedPytest
    work=Path(tempfile.mkdtemp(prefix="strata-autodev-",dir=PRIVATE/"tmp"))
    repo=work/"repo"
    subprocess.run(["/opt/homebrew/bin/gh","repo","clone",
        "quest7070-dev/AI-Foundation",str(repo),"--","--depth","1",
        "--branch",task["base"]],check=True,timeout=90)
    if git(repo,"rev-parse","HEAD")!=task["base_sha"]:
        raise ValueError("PUBLIC_STRATA_BASE_MOVED")
    source=(repo/task["target"]).read_text(encoding="utf-8")
    if hashlib.sha256(source.encode("utf-8")).hexdigest()!=task["source_sha256"]:
        raise ValueError("PUBLIC_STRATA_SOURCE_DRIFT")
    prompt=json.dumps({
        "instruction":task["instruction"],"current_source":source,
        "test_feedback":"Initial implementation; acceptance has not run.",
        "response_format":"Return only the complete replacement file, without Markdown fences.",
    },ensure_ascii=False)
    # If owner-reviewed context cannot fit the existing public egress budget,
    # use original 9B below. No source/test/feedback has left the M1.
    if len(prompt)>4096 or contains_sensitive_value(prompt):
        return None
    tests=FixedPytest(task,repo,work)
    try:tests.run_tests("fixed-host")
    except RuntimeError:pass
    else:raise RuntimeError("BASELINE_ALREADY_PASSES")
    branch="local9b/autonomous-"+task["id"]
    git(repo,"checkout","-b",branch)
    class _OnePublicProposal:
        def __init__(self):self.calls=0
        def run(self,request):
            if self.calls or request.instruction!=prompt:
                raise PermissionError("STRATA_REVIEWED_PROMPT_CHANGED")
            self.calls+=1
            answer=execution.chat(prompt,model="code-agent")
            return AgentResult(compiled_source(answer))
    class _NoM1Lease:
        def hold(self):
            from contextlib import nullcontext
            return nullcontext()
    agent=_OnePublicProposal()
    result=run_local_development_task(
        root=repo,guard=GuardCore(GuardState()),tests=tests,
        proposal_agent=agent,lease=_NoM1Lease(),
        instruction=task["instruction"],target=task["target"],
        acceptance_target="fixed-host-tests",
        repository="quest7070-dev/AI-Foundation",branch=branch,
        base=task["base"],max_repairs=0)
    return {**result.__dict__,"work":str(work),"unattended":True,
            "attempted_binding":"local:mainpc-strata:code-agent",
            "model":"qwen3.8-flash-next-coder-iq1_m",
            "production_activated":False}


def execute(task):
    from local9b_issue_bridge import resolve_task
    task=resolve_task(task)
    # The original pinned M1 9B worker remains the sole fallback on offline
    # public routes, and stays mandatory for all private/unattested tasks.
    offloaded=_try_public_strata_task(task)
    if offloaded is not None:
        return offloaded
    native,_=published_candidate()
    pinned_file(PRIVATE/NATIVE_SEATBELT_NAME,NATIVE_SEATBELT_SHA)
    pinned_file(PRIVATE/V6_PATCH_NAME,V6_PATCH_SHA256)
    work=Path(tempfile.mkdtemp(prefix="autonomous-",dir=PRIVATE/"tmp"))
    repo=work/"repo"
    subprocess.run(["/opt/homebrew/bin/gh","repo","clone","quest7070-dev/AI-Foundation",str(repo),"--","--depth","1","--branch",task["base"]],check=True,timeout=90)
    branch="local9b/autonomous-"+task["id"]
    git(repo,"checkout","-b",branch)
    field=task["field"]
    testcode='import runpy; C=runpy.run_path('+repr(str(repo/"src/ai_foundation/bounded_http.py"))+')["BoundedThreadingHTTPServer"]\n'
    testcode+='for value in [0,-1,True,False,1.5,"2",None]:\n class S(C): '+field+'=value\n try: s=S(("127.0.0.1",0),lambda *a:None)\n except ValueError: pass\n else: s.server_close(); raise AssertionError("invalid accepted: "+repr(value))\n'
    testcode+='class S(C): '+field+'=1\ns=S(("127.0.0.1",0),lambda *a:None);s.server_close()\n'
    policy=work/"accept.sb"
    policy.write_text('(version 1)\n(allow default)\n(deny network-outbound)\n(deny file-write*)\n(allow file-write* (literal "/dev/null"))\n')
    class Tests:
        def run_tests(self,target):
            cp=subprocess.run(["/usr/bin/sandbox-exec","-f",str(policy),"/usr/bin/python3","-B","-c",testcode],capture_output=True,text=True,timeout=15)
            if cp.returncode:raise RuntimeError(cp.stderr[-4000:])
            return "7 invalid request_queue_size cases and valid lifecycle PASS"
    tests=Tests()
    target="src/ai_foundation/bounded_http.py"
    instruction="Fix BoundedThreadingHTTPServer.server_bind to validate "+field+" as a positive integer, rejecting bool, zero, negative and nonintegers with ValueError before semaphore creation and socket bind. Preserve other behavior. Return complete Python source only."
    compact_first = False
    if task.get("recipe")=="python-fixed-test":
        from local9b_task_recipe import FixedPytest
        from ai_foundation.development_compact_edit import compact_first_eligible
        tests=FixedPytest(task,repo,work)
        target=task["target"]
        compact_first = compact_first_eligible(task, repo/target)
        instruction=task["instruction"]
        # The first compact agent requests a JSON search/replace. Asking it
        # simultaneously for full-file source contradicts that contract.
        # Deep repair still receives the development loop's full-file format.
        if not compact_first:
            instruction+=" Return the complete replacement Python source only, without Markdown. Do not change tests."
        fixed_test_text=(repo/task["test"]).read_text()
        if len(fixed_test_text)>16000:raise ValueError("FIXED_TEST_CONTEXT_TOO_LARGE")
        instruction+="\nIndependent fixed acceptance tests:\n"+fixed_test_text
    try:tests.run_tests("fixed-host")
    except RuntimeError:pass
    else:raise RuntimeError("BASELINE_ALREADY_PASSES")
    # Keep the pinned local-only v6 policy; change only the local model output budget.
    budget_patch=PRIVATE/"harness9b-autodev-16384-ctx32768.patch.yml"
    budget_suffix="\n- id: llm-pi-ai\n  config:\n    providers:\n      ollama:\n        api: openai-completions\n        baseURL: http://127.0.0.1:11436/v1\n        apiKeyEnv: OLLAMA_API_KEY\n        models:\n          - id: qwen3.5:9b\n            name: qwen3.5:9b\n            contextWindow: 32768\n            maxTokens: 16384\n"
    budget_bytes=(PRIVATE/V6_PATCH_NAME).read_bytes()+budget_suffix.encode()
    if budget_patch.exists():
        if budget_patch.read_bytes()!=budget_bytes:raise ValueError("MODEL_BUDGET_PATCH_DRIFT")
    else:
        with budget_patch.open("xb") as f:f.write(budget_bytes)
        budget_patch.chmod(0o600)
    env=no_cloud_env(native)
    harness_prefix=("/usr/bin/sandbox-exec","-f",str(PRIVATE/NATIVE_SEATBELT_NAME),
                    str(native/"runtime/node_modules/.bin/dsh"),"--profile","headless","--patch")
    implementation=HarnessProposalAgent(harness_prefix+(str(budget_patch),),str(PRIVATE),env,3600)
    repair_patch=optional_harness_role_patch("REPAIR")
    review_patch=optional_harness_role_patch("REVIEW")
    bindings={"implementation":implementation,
              "repair":(HarnessProposalAgent(harness_prefix+(str(repair_patch),),
                                            str(PRIVATE),env,3600)
                        if repair_patch else implementation)}
    if review_patch:
        bindings["review"]=HostBoundHarnessAgent(
            harness_prefix+(str(review_patch),),str(PRIVATE),env,3600)
    harness_roles=HarnessRoleRuntime(bindings)
    review_gate=HarnessReviewGate(harness_roles) if review_patch else None
    lease=HostComputeLease()
    with lease.hold():
        # CI process/resident daemon presence alone is not inference pressure.
        # This worker starts a SECOND backend, so a loaded shared model still
        # prevents duplicate residency on a memory-constrained host.
        from ai_foundation.local9b_worker_admission import require_dedicated_9b_capacity
        require_dedicated_9b_capacity(
            lambda: api(11434, "ps"), ensure_backend_port_available)
        store=Path.home()/"Library/Application Support/AI-Foundation/direct-apfs-releases/ollama-qwen3-5-9b-56671c2ab9385f9c/models"
        if not store.is_dir():raise RuntimeError("EXISTING_STORE_MISSING")
        with (work/"ollama.log").open("w") as log:
            daemon=subprocess.Popen(["/opt/homebrew/Cellar/ollama/0.34.4/libexec/ollama","serve"],env=dict(os.environ,OLLAMA_HOST="127.0.0.1:11436",OLLAMA_MODELS=str(store),OLLAMA_NUM_PARALLEL="1",OLLAMA_MAX_LOADED_MODELS="1",OLLAMA_CONTEXT_LENGTH="32768"),stdout=log,stderr=log)
            try:
                for _ in range(50):
                    try:
                        tags=api(11436,"tags")
                        if not any(x["name"]=="qwen3.5:9b" and x["digest"]=="56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90" for x in tags["models"]):raise RuntimeError("MODEL_IDENTITY_MISMATCH")
                        break
                    except OSError:time.sleep(.2)
                else:raise RuntimeError("BACKEND_START_FAILED")
                # Inner entry borrows this same flock FD instead of contending with itself.
                class BorrowedLease:
                    def hold(self):
                        from contextlib import nullcontext
                        return nullcontext()
                # For already admitted fixed-Python tests, use the existing
                # exact one-place edit adapter on the first model turn only.
                # Fast path reuses this same local Harness, lease and Guard.
                # Failed compact syntax/tests get the existing full-source
                # REPAIR role (one attempt); all other tasks stay unchanged.
                result=run_local_development_task(root=repo,guard=GuardCore(GuardState()),tests=tests,proposal_agent=harness_roles.agent("implementation"),repair_agent=harness_roles.agent("repair"),review_agent=review_gate,lease=BorrowedLease(),instruction=instruction,target=target,acceptance_target="fixed-host-tests",repository="quest7070-dev/AI-Foundation",branch=branch,base=task["base"],max_repairs=1,compact_single_edit=compact_first)
                return {**result.__dict__,"work":str(work),"unattended":True,"model":"qwen3.5:9b","production_activated":False}
            finally:
                daemon.terminate()
                daemon.wait(timeout=15)

def scheduled_owner_cycle():
    """Run the verified installed M1 CODE host, independently of external MCP."""
    try:
        # This worker runs from its installed immutable bundle; package
        # imports must resolve its own scripts, not a mutable cwd or tunnel.
        from scripts.m1_development_ticket_factory import _owner_local_repo
        from scripts.m1_development_review_candidate import _installed_live_source_repo
        from m1_operator_release_cli import _owner_file
        from m1_direct_development import installed_config
        stage=_installed_live_source_repo(_owner_local_repo())
        child=stage/"scripts/m1_owner_delegated_mcp_stdio.py"
        _owner_file(child,limit=262144)
        config,_,_=installed_config()
        env={key:os.environ[key] for key in ("HOME","USER","TMPDIR","LANG","LC_ALL")
             if type(os.environ.get(key)) is str and os.environ[key]}
        env.update(PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                   PYTHONDONTWRITEBYTECODE="1")
        # No timeout killing a live model child; existing host Work/compute
        # leases and one-shot receipts govern execution and recovery.
        result=subprocess.run([sys.executable,"-B",str(child),
                               "--config",str(config),"--enable-local-development",
                               "--scheduled-cycle"],env=env,cwd=stage,
                              capture_output=True,text=True,check=False)
        row=json.loads(result.stdout)
        state=row.get("state")
        if result.returncode or type(state) is not str or not re.fullmatch(r"[A-Z0-9_]{2,96}",state):
            raise ValueError("SCHEDULED_CYCLE_RECEIPT_UNVERIFIED")
        return {"state":state}
    except Exception:
        return {"state":"SCHEDULED_CYCLE_BLOCKED"}


def main():
    (STATE_ROOT/"inbox").mkdir(exist_ok=True)
    (STATE_ROOT/"results").mkdir(exist_ok=True)
    # The installed M1 host owns the normal work lifecycle. Do not touch
    # GitHub intake, clone, CI or publication before local Work can advance.
    # A failed/uncertain local cycle is not proof that another job is safe.
    cycle=scheduled_owner_cycle()
    write_result(STATE_ROOT/"scheduled-code-cycle.json",cycle)
    print(json.dumps(cycle,sort_keys=True),flush=True)
    if cycle.get("state") not in {"NO_ELIGIBLE_TICKET","SCHEDULED_SCOPE_NOT_ACTIVE"}:
        return
    # Preserve pre-existing, separately authorized legacy Issue work. No new
    # standing regression Issues are created by this normal scheduled path;
    # the installed Work discovery owns new maintenance intake. The legacy
    # exact live Issue check and one-shot claims still apply below.
    from local9b_task_selection import POLICY_VERSION, queued_tasks
    try:
        from local9b_failed_run_intake import capture_failed_run_candidates
        candidates=capture_failed_run_candidates(STATE_ROOT)
        candidate_status="LOCAL_CAPTURED"
    except Exception as e:
        candidates=[]
        candidate_status="BLOCKED:"+type(e).__name__
    try:
        from local9b_issue_bridge import collect_ready
        intake=collect_ready(STATE_ROOT/"inbox")
        standing={"status":"DEFERRED", "reason":"LOCAL_WORK_OWNS_DISCOVERY"}
        write_result(STATE_ROOT/"intake.json",{
            "status":"SUCCESS" if candidate_status=="LOCAL_CAPTURED" else "PARTIAL_SUCCESS",
            "policy":POLICY_VERSION, "issues":intake,
            "new_candidates":candidates,"candidate_collection":candidate_status,
            "standing_main_regression":standing})
    except Exception as e:
        write_result(STATE_ROOT/"intake.json",{"status":"BLOCKED","reason":type(e).__name__,
                                         "policy":POLICY_VERSION})
        return
    from local9b_issue_bridge import previous_issue_attempt
    # Never execute stale, revoked, already attempted or unapproved inbox files.
    # One bounded attempt per scheduled tick; the next eligible Issue is chosen
    # at the next tick using the same explicit, deterministic policy.
    for task_id in queued_tasks(intake):
        path=STATE_ROOT/"inbox"/(task_id+".json")
        if path.is_symlink() or not path.is_file():continue
        out=STATE_ROOT/"results"/path.name
        if out.exists():continue
        # A previously queued revision must not run after *any* other revision
        # of the same Issue started. Check again immediately before claiming.
        # This closes the window between collect_ready() and queue execution.
        match=re.fullmatch(r"issue-([1-9][0-9]*)-[a-f0-9]{16}",path.stem)
        if match and previous_issue_attempt(STATE_ROOT/"inbox",int(match.group(1))):
            continue
        # Atomic, durable ownership across independent workers and revisions.
        # A crash leaves the claim rather than replaying uncertain model work.
        issue_claim=None
        if match:
            issue_claim=STATE_ROOT/"results"/("issue-"+match.group(1)+".claimed")
            try:
                with issue_claim.open("x") as f:f.write(path.name)
            except FileExistsError:
                continue
        started=STATE_ROOT/"results"/(path.stem+".started")
        # Never replay a potentially consumed model task after crash.
        try:
            with started.open("x") as f:f.write(str(time.time()))
        except FileExistsError:
            if issue_claim is not None:issue_claim.unlink()
            continue
        try:
            result=execute(json.loads(path.read_text()))
        except HostComputeBusy:
            # Busy is explicitly before any model use; release our own claims.
            started.unlink()
            if issue_claim is not None:issue_claim.unlink()
            return
        except Exception as e:
            result={"status":"STOPPED","error_type":type(e).__name__,"detail":("MODEL_TURN_TIMEOUT" if isinstance(e,subprocess.TimeoutExpired) else str(e)[-2000:]),"unattended":True}
        write_result(out,result)
        # Never emit paths, model stderr, prompts or exception details in logs.
        print(json.dumps(public_result_status(result),sort_keys=True),flush=True)
        break  # one consumed task per tick; subsequent approved issues are next
if __name__=="__main__":main()
