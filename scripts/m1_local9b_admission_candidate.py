#!/usr/bin/env python3
"""Owned local 9B queue worker. Host-approved finite tasks only; no main merge."""
import os, sys, json, time, subprocess, tempfile, socket, re, errno
from pathlib import Path
from urllib import request

from local9b_worker_paths import configure_worker_paths
ROOT=configure_worker_paths(__file__,state_root=os.environ.get("AI_FOUNDATION_LOCAL9B_STATE_ROOT"))
HARNESS=Path("/Volumes/StorageVolume/home-data/deepseek-harness-standalone/handoff/harness9b-contract-20261106")
sys.path.insert(0,str(HARNESS/"experiments/harness9b"))
from ai_foundation.development_host import HarnessProposalAgent,run_local_development_task
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

def write_result(path,result):
    tmp=path.with_suffix(".tmp");tmp.write_text(json.dumps(result,indent=2));tmp.chmod(0o600);tmp.replace(path)
def execute(task):
    from local9b_issue_bridge import resolve_task
    task=resolve_task(task)
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
    if task.get("recipe")=="python-fixed-test":
        from local9b_task_recipe import FixedPytest
        tests=FixedPytest(task,repo,work)
        target=task["target"]
        instruction=task["instruction"]+" Return the complete replacement Python source only, without Markdown. Do not change tests."
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
    agent=HarnessProposalAgent(("/usr/bin/sandbox-exec","-f",str(PRIVATE/NATIVE_SEATBELT_NAME),str(native/"runtime/node_modules/.bin/dsh"),"--profile","headless","--patch",str(budget_patch)),str(PRIVATE),env,3600)
    lease=HostComputeLease()
    with lease.hold():
        # Process presence is not compute ownership. Keep the shared lease and
        # reject actual shared-model residency before starting a second backend.
        from ai_foundation.klm_compute_admission import AVAILABLE, RESOURCE_UNKNOWN, admit_local_9b
        try:
            shared=api(11434,"ps")
        except (OSError, ValueError, KeyError, TimeoutError):
            raise HostComputeBusy("SHARED_MODEL_STATE_UNKNOWN") from None
        if type(shared) is not dict or type(shared.get("models")) is not list:
            raise HostComputeBusy("SHARED_MODEL_STATE_UNKNOWN")
        if shared["models"]:
            raise HostComputeBusy("SHARED_MODEL_RESIDENT")
        try:
            allowed,reason=admit_local_9b()
        except Exception:
            raise HostComputeBusy(RESOURCE_UNKNOWN) from None
        if allowed is not True or reason != AVAILABLE:
            raise HostComputeBusy(reason if type(reason) is str and reason in
                                  ("CPU_PRESSURE","MEMORY_PRESSURE",RESOURCE_UNKNOWN)
                                  else RESOURCE_UNKNOWN)
        ensure_backend_port_available()
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
                result=run_local_development_task(root=repo,guard=GuardCore(GuardState()),tests=tests,proposal_agent=agent,lease=BorrowedLease(),instruction=instruction,target=target,acceptance_target="fixed-host-tests",repository="quest7070-dev/AI-Foundation",branch=branch,base=task["base"],max_repairs=1)
                return {**result.__dict__,"work":str(work),"unattended":True,"model":"qwen3.5:9b","production_activated":False}
            finally:
                daemon.terminate()
                daemon.wait(timeout=15)

def main():
    from local9b_issue_bridge import collect_ready
    (ROOT/"inbox").mkdir(exist_ok=True)
    (ROOT/"results").mkdir(exist_ok=True)
    from local9b_task_selection import POLICY_VERSION, queued_tasks
    # CI/diagnostic-candidate collection is advisory. A malformed candidate
    # must not disable independently authorized Issue execution.
    try:
        from local9b_failure_candidates import collect_failure_candidates
        candidates=collect_failure_candidates(ROOT)
        candidate_status="SUCCESS"
    except Exception as e:
        candidates=[]
        candidate_status="BLOCKED:"+type(e).__name__
    try:
        intake=collect_ready(ROOT/"inbox")
        write_result(ROOT/"intake.json",{
            "status":"SUCCESS" if candidate_status=="SUCCESS" else "PARTIAL_SUCCESS",
            "policy":POLICY_VERSION, "issues":intake,
            "new_candidates":candidates,"candidate_collection":candidate_status})
    except Exception as e:
        write_result(ROOT/"intake.json",{"status":"BLOCKED","reason":type(e).__name__,
                                         "policy":POLICY_VERSION})
        return
    from local9b_issue_bridge import previous_issue_attempt
    # Never execute stale, revoked, already attempted or unapproved inbox files.
    # One bounded attempt per scheduled tick; the next eligible Issue is chosen
    # at the next tick using the same explicit, deterministic policy.
    for task_id in queued_tasks(intake):
        path=ROOT/"inbox"/(task_id+".json")
        if path.is_symlink() or not path.is_file():continue
        out=ROOT/"results"/path.name
        if out.exists():continue
        # A previously queued revision must not run after *any* other revision
        # of the same Issue started. Check again immediately before claiming.
        # This closes the window between collect_ready() and queue execution.
        match=re.fullmatch(r"issue-([1-9][0-9]*)-[a-f0-9]{16}",path.stem)
        if match and previous_issue_attempt(ROOT/"inbox",int(match.group(1))):
            continue
        # Atomic, durable ownership across independent workers and revisions.
        # A crash leaves the claim rather than replaying uncertain model work.
        issue_claim=None
        if match:
            issue_claim=ROOT/"results"/("issue-"+match.group(1)+".claimed")
            try:
                with issue_claim.open("x") as f:f.write(path.name)
            except FileExistsError:
                continue
        started=ROOT/"results"/(path.stem+".started")
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
        print(json.dumps(result),flush=True)
        break  # one consumed task per tick; subsequent approved issues are next
if __name__=="__main__":main()
