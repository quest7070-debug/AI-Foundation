"""Fail-closed owned Docker fixture cleanup; no Docker daemon or effects in tests."""
import json

import pytest

from scripts import owned_toolhive_probe_cleanup as cleanup


SERVER = "foundation-files-pr183-41817320612-1"
PRODUCTION = "ai-foundation-fs"


def labels(name, *, server=SERVER):
    result = {"toolhive": "true", "toolhive-name": server}
    if name != server:
        result["toolhive-auxiliary-workload"] = "true"
    return result


class FakeDocker:
    def __init__(self, containers):
        self.containers = dict(containers)
        self.removed = []
        self.commands = []

    def __call__(self, args):
        self.commands.append(args)
        if args == ["container", "ls", "-a", "--format", "{{.Names}}"]:
            return "\n".join(sorted(self.containers)) + "\n"
        if args[:4] == ["container", "inspect", "--format", "{{json .Config.Labels}}"]:
            return json.dumps(self.containers[args[4]])
        if args[:3] == ["container", "rm", "--force"]:
            self.removed.append(args[3])
            del self.containers[args[3]]
            return args[3]
        raise AssertionError(f"unexpected command: {args}")


def test_preflight_rejects_existing_exact_family_and_never_removes_it():
    fake = FakeDocker({SERVER: labels(SERVER)})
    with pytest.raises(cleanup.ProbeIdentityError, match="PROBE_IDENTITY_ALREADY_EXISTS"):
        cleanup.preflight(SERVER, fake)
    assert not fake.removed


def test_cleanup_removes_only_verified_run_family_not_running_production():
    family = [SERVER, SERVER + "-dns", SERVER + "-egress"]
    fake = FakeDocker({**{name: labels(name) for name in family},
                       PRODUCTION: labels(PRODUCTION, server=PRODUCTION)})
    assert cleanup.cleanup(SERVER, fake) == 3
    assert set(fake.removed) == set(family)
    assert list(fake.containers) == [PRODUCTION]


def test_cleanup_orphan_dns_without_main_and_is_idempotent():
    name = SERVER + "-dns"
    fake = FakeDocker({name: labels(name)})
    assert cleanup.cleanup(SERVER, fake) == 1
    assert cleanup.cleanup(SERVER, fake) == 0
    assert fake.removed == [name]


@pytest.mark.parametrize("name,label", [
    (SERVER + "-dns", {"toolhive": "true", "toolhive-name": "ai-foundation-fs",
                        "toolhive-auxiliary-workload": "true"}),
    (SERVER + "-dns", {"toolhive": "true", "toolhive-name": SERVER}),
    (SERVER, {"toolhive": "true", "toolhive-name": SERVER,
              "toolhive-auxiliary-workload": "true"}),
    (SERVER + "-dns", {"toolhive-name": SERVER,
                        "toolhive-auxiliary-workload": "true"}),
])
def test_mismatched_identity_or_auxiliary_label_fails_before_any_deletion(name, label):
    fake = FakeDocker({SERVER: labels(SERVER), name: label})
    with pytest.raises(cleanup.ProbeIdentityError):
        cleanup.cleanup(SERVER, fake)
    assert fake.removed == []


def test_unknown_owned_helper_name_fails_before_any_deletion():
    fake = FakeDocker({SERVER: labels(SERVER), SERVER + "-proxy": labels(SERVER + "-proxy")})
    with pytest.raises(cleanup.ProbeIdentityError, match="UNEXPECTED_PROBE_FAMILY_MEMBER"):
        cleanup.cleanup(SERVER, fake)
    assert not fake.removed


def test_malformed_label_json_fails_closed():
    fake = FakeDocker({SERVER: labels(SERVER)})
    def bad(args):
        if args[:2] == ["container", "inspect"]:
            return "not-json"
        return fake(args)
    with pytest.raises(cleanup.ProbeIdentityError, match="PROBE_LABELS_INVALID"):
        cleanup.cleanup(SERVER, bad)
    assert not fake.removed


@pytest.mark.parametrize("name", [PRODUCTION, "foundation-files-pr183-", "../tmp", "", SERVER + ";rm -rf /"])
def test_invalid_probe_name_never_runs_docker(name):
    fake = FakeDocker({SERVER: labels(SERVER)})
    with pytest.raises(cleanup.ProbeIdentityError, match="INVALID_RUN_SCOPED_PROBE_NAME"):
        cleanup.cleanup(name, fake)
    assert fake.commands == []


def test_unexpected_duplicate_inventory_fails_closed():
    fake = FakeDocker({SERVER: labels(SERVER)})
    def duplicate(args):
        if args[:2] == ["container", "ls"]:
            return SERVER + "\n" + SERVER + "\n"
        return fake(args)
    with pytest.raises(cleanup.ProbeIdentityError, match="DOCKER_INVENTORY_AMBIGUOUS"):
        cleanup.cleanup(SERVER, duplicate)
    assert not fake.removed


def test_nonremoval_is_detected_and_cannot_claim_success():
    fake = FakeDocker({SERVER + "-dns": labels(SERVER + "-dns")})
    def stuck(args):
        if args[:3] == ["container", "rm", "--force"]:
            return SERVER + "-dns"
        return fake(args)
    with pytest.raises(cleanup.ProbeIdentityError, match="PROBE_FAMILY_CLEANUP_INCOMPLETE"):
        cleanup.cleanup(SERVER, stuck)
    assert not fake.removed
