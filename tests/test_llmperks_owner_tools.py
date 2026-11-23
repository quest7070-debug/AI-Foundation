"""Synthetic-only acceptance for explicit owner research handoff CLIs."""
from unittest.mock import patch

import pytest

from scripts import llmperks_owner_cycle as cycle
from scripts import llmperks_place_note as place


def test_cycle_inspect_does_not_request_write(capsys):
    result = {"status": "RESEARCH_READBACK_OK", "sha256": "a" * 64}
    with patch.object(cycle, "run", return_value=result) as run:
        assert cycle.main(["--inspect"]) == 0
        run.assert_called_once_with(write=False)
    printed = capsys.readouterr().out
    assert "LLMPERKS_OWNER_DRIVE=RESEARCH_READBACK_OK" in printed
    assert "RESEARCH_SHA256=" in printed


def test_cycle_write_requires_explicit_option(capsys):
    with patch.object(cycle, "run", return_value={"status": "VERIFIED", "sha256": "b" * 64}) as run:
        assert cycle.main(["--write-note"]) == 0
        run.assert_called_once_with(write=True)
    assert "VERIFIED" in capsys.readouterr().out


def test_cycle_error_omits_sensitive_exception_text(capsys):
    with patch.object(cycle, "run", side_effect=RuntimeError("SECRET_KEY_FIXTURE")):
        assert cycle.main(["--inspect"]) == 2
    observed = capsys.readouterr()
    assert "SECRET_KEY_FIXTURE" not in observed.out + observed.err
    assert "UNVERIFIED:RuntimeError" in observed.err


def test_placement_only_passes_explicit_digest_to_host(capsys):
    digest = "c" * 64
    with patch.object(place, "place_owner_note", return_value={
        "status": "RESEARCH_NOTE_ALREADY_IN_FOLDER", "sha256": digest
    }) as run:
        assert place.main(["--sha256", digest]) == 0
        run.assert_called_once_with(digest)
    observed = capsys.readouterr().out
    assert "MODEL_CALLS=0" in observed
    assert "KLM_INTAKE_STAGED=NO" in observed


def test_placement_error_omits_sensitive_exception_text(capsys):
    with patch.object(place, "place_owner_note", side_effect=PermissionError("OWNER_SECRET_FIXTURE")):
        assert place.main(["--sha256", "d" * 64]) == 2
    observed = capsys.readouterr()
    assert "OWNER_SECRET_FIXTURE" not in observed.out + observed.err
    assert "UNVERIFIED:PermissionError" in observed.err
