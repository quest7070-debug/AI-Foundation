import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from types import ModuleType
import sys
import subprocess
import shutil
import os
from contextlib import redirect_stdout
import io
import sqlite3

from scripts import m1_direct_development as direct

REVIEWED_QUOTA_SOURCE = "from dataclasses import dataclass\n\n@dataclass(frozen=True)\nclass QuotaWindow:\n    remaining:float; reset:str|None; source:str\n\ndef _pct(remaining,limit):\n    try:\n        r=float(remaining); l=float(limit)\n        if l<=0: return None\n        return max(0.0,min(100.0,100.0*r/l))\n    except (TypeError,ValueError): return None\n\ndef groq_quota(headers):\n    h={str(k).lower():v for k,v in headers.items()}\n    short=_pct(h.get('x-ratelimit-remaining-tokens'),h.get('x-ratelimit-limit-tokens'))\n    long=_pct(h.get('x-ratelimit-remaining-requests'),h.get('x-ratelimit-limit-requests'))\n    if short is None or long is None: return None\n    return (\n      QuotaWindow(short,h.get('x-ratelimit-reset-tokens'),'groq-response-headers'),\n      QuotaWindow(long,h.get('x-ratelimit-reset-requests'),'groq-response-headers'),\n    )\n\ndef mistral_short_quota(headers):\n    h={str(k).lower():v for k,v in headers.items()}\n    remaining=h.get('x-ratelimit-remaining'); limit=h.get('x-ratelimit-limit')\n    value=_pct(remaining,limit)\n    return QuotaWindow(value,h.get('x-ratelimit-reset'),'mistral-response-headers') if value is not None else None\n"


class DirectDevelopmentTests(unittest.TestCase):
    def test_receipt_requires_manifest_selected_route_and_exact_readback(self):
        m1 = {'state': 'VERIFIED_LOCAL',
              'execution_binding': 'local:ollama-shared9b:general',
              'source_sha256': 'a' * 64}
        strata = dict(m1, execution_binding='local:mainpc-strata:code-agent')
        for model, receipt in (('m1', m1), ('auto', m1), ('auto', strata), ('strata', strata)):
            self.assertTrue(direct.verified_code_receipt(receipt, receipt, receipt, model))
        for model, receipt in (('strata', m1), ('m1', strata), ('unknown', m1)):
            self.assertFalse(direct.verified_code_receipt(receipt, receipt, receipt, model))
        self.assertFalse(direct.verified_code_receipt(m1, dict(m1, source_sha256='b'*64), m1, 'm1'))

    def test_real_quota_baseline_fails_new_independent_acceptance(self):
        namespace = {}
        historical = ModuleType('ai_foundation.provider_quota')
        exec(compile(REVIEWED_QUOTA_SOURCE, 'reviewed-original-source', 'exec'), historical.__dict__)
        with mock.patch.dict(sys.modules, {'ai_foundation.provider_quota': historical}):
            exec(compile(direct.FIXED_TEST, 'fixed-acceptance', 'exec'), namespace)
        with self.assertRaises(AssertionError):
            namespace['test_nonfinite_quota_inputs_are_unknown']()
        # The unchanged valid-input checks pass except the separately asserted
        # nonfinite provider wrapper case; this is a real source defect.
        from ai_foundation.provider_quota import _pct
        self.assertEqual(_pct('25', '100'), 25)

    def test_review_hash_and_manifest_are_exact_without_delivery_grant(self):
        source = REVIEWED_QUOTA_SOURCE.encode()
        ticket = direct.manifest_ticket('a' * 40, source)
        self.assertEqual(ticket['public_source_sha256'], ticket['source_sha256'])
        self.assertEqual(ticket['model'], 'strata')
        self.assertNotIn('allow_draft_delivery', ticket)
        with self.assertRaises(ValueError):
            direct.manifest_ticket('a' * 40, source + b'\n')

    def test_missing_strata_key_never_starts_ticket_or_child(self):
        import ai_foundation.local_endpoint_config as endpoints
        with mock.patch.object(direct, 'installed_config', return_value=(None, None, Path('/unused'))), mock.patch.object(endpoints, 'load_local_endpoints', return_value=()), mock.patch.object(direct.subprocess, 'run') as child:
            result = direct.client(True)
        self.assertEqual(result['ticket_started'], False)
        self.assertEqual(result['model_calls'], 0)
        child.assert_not_called()

    def test_write_readback_and_replay_use_separate_mcp_calls(self):
        import ai_foundation.local_endpoint_config as endpoints
        report = {'ticket_id':direct.TICKET,'state':'VERIFIED_LOCAL',
                  'execution_binding':'local:mainpc-strata:code-agent', 'source_sha256':'b'*64}
        def result(id_, body):
            return {'jsonrpc':'2.0','id':id_,'result':{'isError':False,'content':[{'type':'text','text':json.dumps(body)}]}}
        rows=[{'id':1,'result':{}},{'id':2,'result':{}},result(3,{'state':'READY'}),result(4,report)]
        fresh=[{'id':1,'result':{}},{'id':2,'result':{}},result(3,report),result(4,report)]
        discovery=SimpleNamespace(candidates=lambda:[SimpleNamespace(binding='local:mainpc-strata:code-agent',health='ONLINE',same_host=False,capabilities=('CODE',))])
        entries=(('local:mainpc-strata',discovery,SimpleNamespace(api_key='SYNTHETIC_PRIVATE_KEY',models={'code-agent':'qwen3.8-flash-next-coder-iq1_m'})),)
        child=SimpleNamespace(returncode=0,stdout='\n'.join(json.dumps(r) for r in rows))
        refreshed=SimpleNamespace(returncode=0,stdout='\n'.join(json.dumps(r) for r in fresh))
        with mock.patch.object(direct,'installed_config',return_value=(None,None,Path('/unused'))), mock.patch.object(endpoints,'load_local_endpoints',return_value=entries), mock.patch.object(direct.subprocess,'run',side_effect=[child,refreshed]) as run, mock.patch.dict(os.environ,{'STRATA_API_KEY':'SYNTHETIC_OWNER_KEY','GITHUB_TOKEN':'MUST_NOT_INHERIT'}):
            observed=direct.client(True)
        self.assertEqual(observed['status'],'MCP_CODE_VERIFIED')
        first=[json.loads(l) for l in run.call_args_list[0].kwargs['input'].splitlines()]
        second=[json.loads(l) for l in run.call_args_list[1].kwargs['input'].splitlines()]
        self.assertEqual([r['params'].get('name') for r in first[2:]],['development_status','development_run'])
        self.assertEqual([r['params'].get('name') for r in second[2:]],['development_status','development_run'])
        self.assertNotIn('GITHUB_TOKEN',run.call_args.kwargs['env'])
        self.assertEqual(run.call_args.kwargs['env']['STRATA_API_KEY'],'SYNTHETIC_OWNER_KEY')
        self.assertFalse(observed['cloud_chatgpt_muse_connection_verified'])

    def test_external_stdio_cannot_consume_fresh_ticket_without_strata(self):
        port=mock.Mock()
        port.status.return_value={'state':'READY'}
        ready=mock.Mock(return_value=False)
        gated=direct.StrataReadyPort(port,ready)
        self.assertEqual(gated.run('owner',direct.TICKET)['state'],'WAITING_STRATA')
        port.run.assert_not_called()
        port.status.return_value={'state':'VERIFIED_LOCAL'}
        self.assertEqual(gated.run('owner',direct.TICKET)['state'],'VERIFIED_LOCAL')
        self.assertEqual(ready.call_count,1)

    def test_second_reviewed_strata_ticket_is_independently_gated(self):
        port=mock.Mock()
        port.status.return_value={'state':'READY'}
        gated=direct.StrataReadyPort(
            port, lambda ticket_id: False, strict_tickets=('next-public-code',))
        denied=gated.run('owner','next-public-code')
        self.assertEqual(denied['state'],'WAITING_STRATA')
        self.assertFalse(denied['github_published'])
        port.run.assert_not_called()
        port.status.return_value={'state':'VERIFIED_LOCAL'}
        self.assertEqual(gated.run('owner','next-public-code')['state'],'VERIFIED_LOCAL')
        port.run.assert_not_called()

    def test_waiting_first_run_never_replays_in_fresh_session(self):
        def result(id_,body):
            return {'id':id_,'result':{'isError':False,'content':[{'text':json.dumps(body)}]}}
        rows=[{'id':1},{'id':2},result(3,{'state':'READY'}),result(4,{'state':'WAITING_STRATA'})]
        child=SimpleNamespace(returncode=0,stdout='\n'.join(json.dumps(r) for r in rows))
        with mock.patch.object(direct,'installed_config',return_value=(None,None,Path('/unused'))),mock.patch.object(direct,'strata_ready',return_value=True),mock.patch.object(direct.subprocess,'run',return_value=child) as run:
            observed=direct.client(True)
        self.assertEqual(observed['ticket']['state'],'WAITING_STRATA')
        self.assertEqual(run.call_count,1)

    def test_install_run_executes_persistent_launcher_not_bootstrap_client(self):
        installation={'status':'DIRECT_DEVELOPMENT_INSTALLED','launcher':'/owner/foundation'}
        child=SimpleNamespace(returncode=0,stdout=json.dumps({'status':'MCP_CODE_VERIFIED'}))
        output=io.StringIO()
        host=SimpleNamespace(require_m1=lambda:None)
        with mock.patch.dict(sys.modules,{'m1_development_bridge':host}),mock.patch.object(sys,'argv',['direct','install-run']),mock.patch.object(direct.os,'getuid',return_value=501),mock.patch.object(direct.os,'geteuid',return_value=501),mock.patch.object(direct,'install',return_value=installation),mock.patch.object(direct.subprocess,'run',return_value=child) as run,mock.patch.object(direct,'client') as disposable,redirect_stdout(output):
            self.assertEqual(direct.main(),0)
        self.assertEqual(run.call_args.args[0],['/owner/foundation','run'])
        disposable.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())['installation'],installation)

    def test_diagnose_is_readonly_and_never_exports_private_results_or_config(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            config=SimpleNamespace(work_db='work.db',guard_db='guard.db')
            job='mcp-local-development:'+direct.sha256(json.dumps(['macos-owner-local',direct.TICKET],separators=(',',':')).encode()).hexdigest()
            with sqlite3.connect(root/'work.db') as db:
                db.execute('CREATE TABLE work_steps(job_id,position,status,result)')
                db.execute('INSERT INTO work_steps VALUES(?,?,?,?)',(job,0,'FAILED','PRIVATE_TEST_FEEDBACK'))
            with sqlite3.connect(root/'guard.db') as db:
                db.execute('CREATE TABLE effects(target,status)')
            path=root/'local-compute/endpoints.json'
            path.parent.mkdir()
            path.write_text(json.dumps({'endpoints':[{'name':'mainpc-strata','api_key':'PRIVATE_KEY','request_defaults':{'max_tokens':4096}}]}))
            source=root/'development/worktrees'/direct.TICKET/direct.TARGET
            source.parent.mkdir(parents=True)
            source.write_text(REVIEWED_QUOTA_SOURCE)
            before=(root/'work.db').read_bytes()
            with mock.patch.object(direct,'installed_config',return_value=(None,config,root)),mock.patch.object(direct.subprocess,'run') as run:
                report=direct.diagnose()
            self.assertFalse(report['source_changed'])
            self.assertEqual(report['execution_timeout_seconds'],120)
            self.assertEqual(report['failure_code'],'NOT_A_FIXED_FAILURE_CODE')
            self.assertEqual(report['work_state'],'FAILED')
            self.assertNotIn('PRIVATE',json.dumps(report))
            self.assertNotIn(str(root),json.dumps(report))
            self.assertEqual((root/'work.db').read_bytes(),before)
            run.assert_not_called()

    def test_r2_timeout_change_is_private_exact_and_idempotent(self):
        self.assertNotEqual(direct.TICKET, 'strata-quota-finite-20261114')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'local-compute/endpoints.json'
            path.parent.mkdir(mode=0o700)
            original = {'version': 1, 'endpoints': [
                {'name': 'mainpc-strata', 'base_url': 'http://10.0.1.1:18080',
                 'optional': True, 'timeout': 120, 'api_key_env': 'STRATA_API_KEY'},
                {'name': 'other-local', 'timeout': 15}]}
            path.write_text(json.dumps(original))
            path.chmod(0o600)
            self.assertEqual(direct.ensure_strata_timeout(root), 300)
            changed = json.loads(path.read_text())
            self.assertEqual(changed['endpoints'][0]['timeout'], 300)
            self.assertEqual(changed['endpoints'][1], original['endpoints'][1])
            self.assertEqual(path.stat().st_mode & 0o077, 0)
            before = path.read_bytes()
            self.assertEqual(direct.ensure_strata_timeout(root), 300)
            self.assertEqual(path.read_bytes(), before)
            changed['endpoints'][0]['timeout'] = 301
            path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                direct.ensure_strata_timeout(root)
            self.assertEqual(json.loads(path.read_text())['endpoints'][0]['timeout'], 301)

    def test_draft_delivery_auth_requires_native_owner_not_actions_bot(self):
        with mock.patch.object(direct.subprocess, "run", return_value=SimpleNamespace(
                returncode=0, stdout="github-actions[bot]\n")) as run, mock.patch.dict(
                os.environ, {"GITHUB_TOKEN": "MUST_NOT_PASS", "GH_TOKEN": "MUST_NOT_PASS"}):
            self.assertFalse(direct.owner_gh_authenticated())
        self.assertNotIn("GITHUB_TOKEN", run.call_args.kwargs["env"])
        self.assertNotIn("GH_TOKEN", run.call_args.kwargs["env"])
        with mock.patch.object(direct.subprocess, "run", return_value=SimpleNamespace(
                returncode=0, stdout="quest7070-debug\n")):
            self.assertTrue(direct.owner_gh_authenticated())

    def test_exact_verified_delivery_grant_checks_work_and_preserves_existing_receipt(self):
        from ai_foundation.development_host import HostBoundLocalDevelopmentPort
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            development = root / "development"
            development.mkdir(mode=0o700)
            manifest = development / "tickets.json"
            record = direct.manifest_ticket("a" * 40, REVIEWED_QUOTA_SOURCE.encode())
            manifest.write_text(json.dumps({"version": 1, "tickets": [record]}))
            manifest.chmod(0o600)
            source = development / "worktrees" / direct.TICKET / direct.TARGET
            source.parent.mkdir(parents=True)
            source.write_text(REVIEWED_QUOTA_SOURCE)
            expected = direct.sha256(source.read_bytes()).hexdigest()
            config = SimpleNamespace(work_db="work.db")
            job = HostBoundLocalDevelopmentPort._job_id(direct.TICKET, "macos-owner-local")
            with sqlite3.connect(root / "work.db") as db:
                db.execute("CREATE TABLE work_steps(job_id,position,status,result)")
                db.execute("INSERT INTO work_steps VALUES(?,?,?,?)",
                           (job, 0, "VERIFIED", json.dumps({
                               "status": "TESTED_CHANGE", "sha256": expected,
                               "execution_binding": "local:mainpc-strata:code-agent"})))
            before = (root / "work.db").read_bytes()
            with mock.patch.object(direct, "installed_config", return_value=(None, config, root)), mock.patch.object(
                direct, "VERIFIED_R2_SHA", expected), mock.patch.object(direct.subprocess, "run") as child:
                self.assertEqual(direct.authorize_verified_delivery()["status"], "EXACT_DRAFT_DELIVERY_GRANTED")
                changed = manifest.read_bytes()
                self.assertTrue(json.loads(changed)["tickets"][0]["allow_draft_delivery"])
                self.assertEqual(direct.authorize_verified_delivery()["status"], "EXACT_DRAFT_DELIVERY_GRANTED")
                self.assertEqual(manifest.read_bytes(), changed)
                source.write_text(REVIEWED_QUOTA_SOURCE + "\n# changed")
                with self.assertRaises(ValueError):
                    direct.authorize_verified_delivery()
                child.assert_not_called()
            self.assertEqual((root / "work.db").read_bytes(), before)

    def test_draft_delivery_mcp_readback_never_reexecutes_model(self):
        def frame(id_, body):
            return {"id": id_, "result": {"isError": False,
                    "content": [{"type": "text", "text": json.dumps(body)}]}}
        expected = direct.VERIFIED_R2_SHA
        before = {"state": "VERIFIED_LOCAL", "ticket_id": direct.TICKET,
                  "source_sha256": expected, "github_published": False}
        published = {"state": "VERIFIED_LOCAL", "ticket_id": direct.TICKET,
                     "source_sha256": expected, "github_published": True,
                     "draft_pr_url": "https://github.com/quest7070-dev/AI-Foundation/pull/1234"}
        first = [{"id": 1}, {"id": 2}, frame(3, before), frame(4, published)]
        second = [{"id": 1}, {"id": 2}, frame(3, published), frame(4, published)]
        child = [SimpleNamespace(returncode=0, stdout="\n".join(json.dumps(x) for x in rows))
                 for rows in (first, second)]
        with mock.patch.object(direct.subprocess, "run", side_effect=child) as run, mock.patch.dict(
                os.environ, {"GH_TOKEN": "SYNTHETIC_GH_TOKEN",
                             "GITHUB_TOKEN": "MUST_NOT_PASS", "STRATA_API_KEY": "MUST_NOT_PASS"}):
            result = direct.deliver_client()
        self.assertEqual(result["status"], "DRAFT_DELIVERY_VERIFIED")
        self.assertTrue(result["durable_readback_matches"])
        self.assertTrue(result["replay_readonly"])
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            requests = [json.loads(line) for line in call.kwargs["input"].splitlines()]
            self.assertEqual([x["params"]["name"] for x in requests[2:]],
                             ["development_status", "development_deliver"])
            self.assertEqual(call.kwargs["env"]["GH_TOKEN"], "SYNTHETIC_GH_TOKEN")
            self.assertNotIn("GITHUB_TOKEN", call.kwargs["env"])
            self.assertNotIn("STRATA_API_KEY", call.kwargs["env"])

    def test_no_local_model_fallback_or_unreviewed_commands(self):
        with self.assertRaises(RuntimeError):
            direct.NoM1Fallback().chat('unused')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'private.json'
            direct.write_private(path,'{}')
            self.assertEqual(path.stat().st_mode & 0o077,0)
            alias=Path(folder)/'alias'
            alias.symlink_to(path)
            with self.assertRaises(ValueError):
                direct.write_private(alias,'changed')

    def test_install_is_idempotent_and_preserves_owner_main(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder)/'owner'
            repo=home/'Develop/AI-Foundation'
            repo.mkdir(parents=True)
            (repo/direct.TARGET).parent.mkdir(parents=True)
            (repo/direct.TARGET).write_text(REVIEWED_QUOTA_SOURCE)
            (repo/'tests').mkdir()
            (repo/'tests/.keep').write_text('fixture')
            subprocess.run(['git','init','-q',str(repo)],check=True)
            direct.git(repo,'add','.')
            direct.git(repo,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','original')
            before=direct.git(repo,'rev-parse','HEAD')
            python=repo/'.venv/bin/python'
            python.parent.mkdir(parents=True)
            python.write_text('fixture')
            # Ignore the existing virtualenv exactly as a normal owner checkout.
            (repo/'.git/info/exclude').write_text('.venv/\n')
            bootstrap=Path(folder)/'disposable-bootstrap'
            subprocess.run(['git','clone','-q','--no-hardlinks',str(repo),str(bootstrap)],check=True)
            (bootstrap/'release-marker').write_text('new reviewed release')
            direct.git(bootstrap,'add','release-marker')
            direct.git(bootstrap,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','reviewed release')
            data=home/'private-data'
            data.mkdir(mode=0o700)
            def directory(path):
                path.mkdir(mode=0o700,parents=True,exist_ok=True)
                return path
            helper=SimpleNamespace(_owner_file=lambda p:p.read_bytes(),_strict_json=json.loads,_validate_ticket=lambda r:None)
            with mock.patch.object(direct,'ROOT',bootstrap),mock.patch.object(direct,'installed_config',return_value=(None,None,data)),mock.patch.object(direct,'private_dir',side_effect=directory),mock.patch.object(Path,'home',return_value=home),mock.patch.dict(sys.modules,{'m1_development_ticket_factory':helper}),mock.patch.object(direct,'ensure_strata_timeout',return_value=300):
                first=direct.install()
                second=direct.install()
            self.assertEqual(first,second)
            self.assertEqual(direct.git(repo,'rev-parse','HEAD'),before)
            self.assertEqual(direct.git(repo,'status','--porcelain'),'')
            manifest=data/'development/tickets.json'
            self.assertEqual(len(json.loads(manifest.read_text())['tickets']),1)
            self.assertEqual(manifest.stat().st_mode & 0o077,0)
            self.assertEqual((home/'foundation').stat().st_mode & 0o777,0o700)
            shutil.rmtree(bootstrap)
            runtime=data/'development/runtime'/first['revision']
            self.assertEqual(direct.git(runtime,'status','--porcelain'),'')
            self.assertIn(str(repo/'.git'),(runtime/'.git').read_text())


    def test_ready_strata_ticket_can_wake_once_before_guarded_run(self):
        port = mock.Mock()
        port.status.return_value = {"state": "READY"}
        port.run.return_value = {"state": "VERIFIED_LOCAL"}
        ready = mock.Mock(side_effect=[False, True])
        wake = mock.Mock(return_value=True)
        gated = direct.StrataReadyPort(
            port, ready, strict_tickets=("fresh-public",), wake=wake,
            wake_tickets=("fresh-public",))
        self.assertEqual(gated.run("owner", "fresh-public")["state"], "VERIFIED_LOCAL")
        wake.assert_called_once_with("fresh-public")
        port.run.assert_called_once_with("owner", "fresh-public")
        # Reopening a verified ticket may only return its existing status.
        port.status.return_value = {"state": "VERIFIED_LOCAL"}
        self.assertEqual(gated.run("owner", "fresh-public")["state"], "VERIFIED_LOCAL")
        wake.assert_called_once()

    def test_auto_wakes_first_but_m1_only_never_wakes(self):
        port = mock.Mock()
        port.status.return_value = {"state": "READY"}
        port.run.return_value = {"state": "VERIFIED_LOCAL"}
        wake = mock.Mock(return_value=False)
        ready = mock.Mock(return_value=True)  # M1 is eligible for fallback.
        gated = direct.StrataReadyPort(
            port, ready, strict_tickets=("fresh-auto", "m1-only"),
            waiting_state="WAITING_M1", wake=wake,
            wake_first_tickets=("fresh-auto",), wake_tickets=("fresh-auto",))
        self.assertEqual(gated.run("owner", "fresh-auto")["state"], "VERIFIED_LOCAL")
        wake.assert_called_once_with("fresh-auto")
        self.assertEqual(gated.run("owner", "m1-only")["state"], "VERIFIED_LOCAL")
        wake.assert_called_once()  # Private/M1-only work has no PC effect.

    def test_m1_only_capacity_pressure_cannot_use_strata_wake(self):
        port = mock.Mock()
        port.status.return_value = {"state": "READY"}
        ready = mock.Mock(return_value=False)
        wake = mock.Mock(side_effect=AssertionError("private M1 task must not wake PC"))
        gated = direct.StrataReadyPort(
            port, ready, strict_tickets=("m1-private", "fresh-auto"),
            waiting_state="WAITING_M1", wake=wake,
            wake_first_tickets=("fresh-auto",), wake_tickets=("fresh-auto",))
        self.assertEqual(gated.run("owner", "m1-private")["state"], "WAITING_M1")
        wake.assert_not_called()
        port.run.assert_not_called()

    def test_nonready_reviewed_tickets_never_probe_capacity_or_wake(self):
        for state in ("REVIEW_REQUIRED", "CANCELLED", "FAILED_REVIEW_REQUIRED",
                      "VERIFIED_LOCAL", "SOURCE_BASE_REVIEW_REQUIRED", "RUNNING"):
            with self.subTest(state=state):
                port = mock.Mock()
                port.status.return_value = {"state": state}
                ready, wake = mock.Mock(), mock.Mock()
                gated = direct.StrataReadyPort(
                    port, ready, strict_tickets=("fresh-auto",), wake=wake,
                    wake_first_tickets=("fresh-auto",), wake_tickets=("fresh-auto",))
                self.assertEqual(gated.run("owner", "fresh-auto")["state"], state)
                ready.assert_not_called()
                wake.assert_not_called()
                port.run.assert_not_called()
                gated.status("owner", "fresh-auto")
                gated.list_tickets("owner", authorize_status=lambda _: True)
                wake.assert_not_called()

    def test_pending_and_cancelled_mcp_request_cannot_reach_wake(self):
        from ai_foundation.development_requests import DevelopmentRequestPort
        from ai_foundation.durable_work import SQLiteWorkStore
        from ai_foundation.orchestration import WorkStatus
        with tempfile.TemporaryDirectory() as folder:
            work = SQLiteWorkStore(Path(folder) / "work.sqlite")
            base = mock.Mock()
            base.guard = object()
            base.authorize.return_value = False
            base.status.return_value = {"state": "READY"}
            wake = mock.Mock(side_effect=AssertionError("unreviewed request must not wake"))
            gated = direct.StrataReadyPort(
                base, mock.Mock(return_value=False), strict_tickets=("fresh-auto",),
                wake=wake, wake_first_tickets=("fresh-auto",), wake_tickets=("fresh-auto",))
            port = DevelopmentRequestPort(
                gated, work=work, principal_id="owner",
                storage_admission=SimpleNamespace(require=lambda _: None))
            principal = SimpleNamespace(principal_id="owner")
            port.request(principal, "fresh-auto", "Public CODE improvement")
            base.authorize.return_value = True  # Partial manifest admission alone is insufficient.
            self.assertEqual(port.run(principal, "fresh-auto")["state"], "REVIEW_REQUIRED")
            job = port.prefix + "fresh-auto"
            work.transition(job, 0, WorkStatus.WAITING_HUMAN, WorkStatus.CANCELLED)
            self.assertEqual(port.run(principal, "fresh-auto")["state"], "CANCELLED")
            wake.assert_not_called()
            base.run.assert_not_called()

    def test_owner_wake_intent_is_persisted_before_one_shot_preflight(self):
        import re
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "development").mkdir(mode=0o700)
            def probe_model(_path, *, wake, smoke, diagnostics=None):
                if not wake:
                    diagnostics["reason_code"] = "DISCOVERY_URLError"
                    return {"status": "MAINPC_UNAVAILABLE"}
                self.assertTrue(smoke)
                return {"status": "INFERENCE_VERIFIED"}
            called = mock.Mock(side_effect=probe_model)
            bridge = SimpleNamespace(require_m1=lambda: None)
            factory = SimpleNamespace(_ID=re.compile(r"[a-z0-9][a-z0-9-]{0,47}\Z"))
            preflight = SimpleNamespace(verify_strata=called)
            def private(path):
                path.mkdir(mode=0o700, parents=True, exist_ok=True)
                return path
            with mock.patch.dict(sys.modules, {
                    "m1_development_bridge": bridge,
                    "m1_development_ticket_factory": factory,
                    "mainpc_strata_preflight": preflight}), \
                 mock.patch.object(direct.os, "getuid", return_value=501), \
                 mock.patch.object(direct.os, "geteuid", return_value=501), \
                 mock.patch.object(direct, "strata_configured", return_value=True), \
                 mock.patch.object(direct, "strata_ready", side_effect=[False, True, False]), \
                 mock.patch.object(direct, "private_dir", side_effect=private):
                self.assertTrue(direct.wake_strata_once(root, "fresh-public"))
                self.assertFalse(direct.wake_strata_once(root, "fresh-public"))
            # The later read-only status probe is allowed; the physical
            # wake effect itself must remain a single occurrence.
            self.assertEqual(called.call_count, 3)
            self.assertEqual(sum(bool(call.kwargs["wake"])
                                 for call in called.call_args_list), 1)
            called.assert_any_call(
                root.resolve(strict=True) / "local-compute/endpoints.json",
                wake=False, smoke=False, diagnostics=mock.ANY)
            called.assert_any_call(
                root.resolve(strict=True) / "local-compute/endpoints.json",
                wake=True, smoke=True)
            marker = root / "development/strata-wake-intents/fresh-public.intent"
            self.assertTrue(marker.is_file())
            self.assertEqual(marker.stat().st_mode & 0o077, 0)

    def test_wake_without_verified_inference_never_admits_strata(self):
        import re
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "development").mkdir(mode=0o700)
            calls = []
            def probe(_path, *, wake, smoke, diagnostics=None):
                calls.append((wake, smoke))
                if not wake:
                    diagnostics["reason_code"] = "DISCOVERY_URLError"
                    return {"status": "MAINPC_UNAVAILABLE"}
                return {"status": "INFERENCE_UNAVAILABLE"}
            modules = {
                "m1_development_bridge": SimpleNamespace(require_m1=lambda: None),
                "m1_development_ticket_factory": SimpleNamespace(
                    _ID=re.compile(r"[a-z0-9][a-z0-9-]{0,47}\Z")),
                "mainpc_strata_preflight": SimpleNamespace(
                    verify_strata=mock.Mock(side_effect=probe)),
            }
            with mock.patch.dict(sys.modules, modules), \
                 mock.patch.object(direct.os, "getuid", return_value=501), \
                 mock.patch.object(direct.os, "geteuid", return_value=501), \
                 mock.patch.object(direct, "strata_configured", return_value=True), \
                 mock.patch.object(direct, "strata_ready", return_value=False), \
                 mock.patch.object(direct, "private_dir", side_effect=lambda p: (
                     p.mkdir(parents=True, mode=0o700, exist_ok=True) or p)):
                self.assertFalse(direct.wake_strata_once(root, "fresh-public"))
                self.assertFalse(direct.wake_strata_once(root, "fresh-public"))
            self.assertEqual(calls, [(False, False), (True, True), (False, False)])
            self.assertEqual(sum(wake for wake, _smoke in calls), 1)
            self.assertTrue((root / "development/strata-wake-intents/fresh-public.intent").exists())

    def test_auth_failure_never_consumes_one_shot_wake_intent(self):
        import re
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "development").mkdir(mode=0o700)
            bridge = SimpleNamespace(require_m1=lambda: None)
            factory = SimpleNamespace(_ID=re.compile(r"[a-z0-9][a-z0-9-]{0,47}\Z"))
            def auth_failed(_path, *, wake, smoke, diagnostics=None):
                if diagnostics is not None:
                    diagnostics["reason_code"] = "DISCOVERY_HTTP_401"
                self.assertFalse(wake)
                return {"status": "MAINPC_UNAVAILABLE"}
            preflight = SimpleNamespace(verify_strata=mock.Mock(side_effect=auth_failed))
            with mock.patch.dict(sys.modules, {
                    "m1_development_bridge": bridge,
                    "m1_development_ticket_factory": factory,
                    "mainpc_strata_preflight": preflight}), \
                 mock.patch.object(direct.os, "getuid", return_value=501), \
                 mock.patch.object(direct.os, "geteuid", return_value=501), \
                 mock.patch.object(direct, "strata_configured", return_value=True), \
                 mock.patch.object(direct, "strata_ready", return_value=False):
                self.assertFalse(direct.wake_strata_once(root, "fresh-public"))
            self.assertFalse(
                (root / "development/strata-wake-intents/fresh-public.intent").exists())
            preflight.verify_strata.assert_called_once()

    def test_no_wake_if_not_owner_or_unreviewed_binding(self):
        with mock.patch.object(direct.os, "getuid", return_value=502), \
             mock.patch.object(direct.os, "geteuid", return_value=502), \
             mock.patch.dict(sys.modules, {
                 "m1_development_bridge": SimpleNamespace(require_m1=lambda: None),
                 "m1_development_ticket_factory": SimpleNamespace(
                     _ID=__import__("re").compile(r"[a-z0-9-]+\Z"))}), \
             mock.patch.object(direct, "strata_configured") as creds:
            self.assertFalse(direct.wake_strata_once("/unused", "fresh-public"))
            creds.assert_not_called()


if __name__=='__main__':
    unittest.main()

