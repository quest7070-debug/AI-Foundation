"""Ownership-only #223 source contracts; no RAM/page/swap admission."""
import dataclasses
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiments.m1_host_admission.proposal import Evidence, Request, Resident, assess

D = "a" * 64


def baseline():
    request = Request(
        alias="local-general", bound_alias="local-general",
        expected_digest=D, observed_digest=D,
        required_role="CHAT", host_roles=frozenset({"CHAT"}),
        provider="LOCAL_ONLY")
    evidence = Evidence(
        captured_at_ms=1000, checked_at_ms=1100,
        endpoints_verified=True, lock_held=True, job_scope_verified=True,
        runner_uids_coordinated=True, runner_uid=501, lease_uid=501,
        other_ci_active=False, shared_ollama_clients="NONE", residents=())
    return request, evidence


class OwnerAdmissionContracts(unittest.TestCase):
    def check(self, status, request=None, evidence=None):
        r, e = baseline()
        result=assess(r if request is None else request,
                      e if evidence is None else evidence)
        self.assertEqual(result["status"],status,result)
        self.assertIs(result["effect_authorized"],False)
        self.assertEqual(result["model_calls"],0)
        self.assertNotIn("required_bytes",result)
        self.assertNotIn("free_bytes",result)
        return result

    def test_owner_only_pass_never_authorizes_effect(self):
        result=self.check("ADMIT")
        self.assertEqual(result["reason"],"OWNER_PRECHECK_PASSED_NO_EFFECT")

    def test_lease_and_ci_contention(self):
        r,e=baseline()
        self.check("DEFER_RESOURCE_BUSY",evidence=dataclasses.replace(e,lock_held=False))
        self.check("DEFER_RESOURCE_BUSY",evidence=dataclasses.replace(e,other_ci_active=True))

    def test_job_scope_and_runner_uid(self):
        r,e=baseline()
        self.check("DEFER_UNCOORDINATED_CLIENT",evidence=dataclasses.replace(e,job_scope_verified=False))
        self.check("DEFER_UNCOORDINATED_CLIENT",evidence=dataclasses.replace(e,runner_uids_coordinated=False))
        self.check("DEFER_UNCOORDINATED_CLIENT",evidence=dataclasses.replace(e,lease_uid=502))

    def test_other_clients_are_not_silently_evicted(self):
        r,e=baseline()
        for client in ("ACTIVE","UNKNOWN"):
            self.check("DEFER_UNCOORDINATED_CLIENT",
                       evidence=dataclasses.replace(e,shared_ollama_clients=client))
        self.check("DEFER_UNCOORDINATED_CLIENT",
                   evidence=dataclasses.replace(e,residents=(Resident("other","EXTERNAL"),)))

    def test_cooperating_residents_can_be_inventoried_without_size(self):
        r,e=baseline()
        result=self.check("ADMIT",evidence=dataclasses.replace(
            e,residents=(Resident("one","COOPERATING"),Resident("two","COOPERATING"))))
        self.assertEqual(result["resident_count"],2)

    def test_invalid_or_duplicate_residents(self):
        r,e=baseline()
        self.check("INVALID_OWNERSHIP_EVIDENCE",
                   evidence=dataclasses.replace(e,residents=(
                       Resident("same","COOPERATING"),Resident("same","COOPERATING"))))
        self.check("INVALID_OWNERSHIP_EVIDENCE",
                   evidence=dataclasses.replace(e,residents=None))

    def test_expired_or_invalid_clock(self):
        r,e=baseline()
        self.check("INVALID_OWNERSHIP_EVIDENCE",
                   evidence=dataclasses.replace(e,checked_at_ms=9000))
        self.check("INVALID_OWNERSHIP_EVIDENCE",
                   evidence=dataclasses.replace(e,checked_at_ms=900))
        self.check("INVALID_OWNERSHIP_EVIDENCE",
                   evidence=dataclasses.replace(e,runner_uid=True))

    def test_role_digest_and_provider_binding(self):
        r,e=baseline()
        for req in (
            dataclasses.replace(r,observed_digest="b"*64),
            dataclasses.replace(r,bound_alias="different"),
            dataclasses.replace(r,required_role="CODE"),
            dataclasses.replace(r,provider="CLOUD"),
            dataclasses.replace(r,expected_digest="invalid"),
        ):
            self.check("INVALID_OWNERSHIP_EVIDENCE",request=req)

    def test_endpoint_unknown_invalid(self):
        r,e=baseline()
        self.check("INVALID_OWNERSHIP_EVIDENCE",
                   evidence=dataclasses.replace(e,endpoints_verified=False))

    def test_no_memory_fields_in_dataclass_contract(self):
        self.assertEqual(set(Evidence.__dataclass_fields__),{
            "captured_at_ms","checked_at_ms","endpoints_verified","lock_held",
            "job_scope_verified","runner_uids_coordinated","runner_uid","lease_uid",
            "other_ci_active","shared_ollama_clients","residents"})
        self.assertEqual(set(Request.__dataclass_fields__),{
            "alias","bound_alias","expected_digest","observed_digest",
            "required_role","host_roles","provider"})


if __name__=="__main__":
    unittest.main()
