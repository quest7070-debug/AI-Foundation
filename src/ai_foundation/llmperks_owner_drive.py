"""Owner-only LLMPerks research handoff via the existing Drive app-file port.

This module never reuses KLM's readonly token. The optional production adapter
is the EXISTING PR #481 development_drive_text_runtime.text_port: the same
owner-consented drive.file scope, owner Keychain and stable owner lock.

No content is submitted to inference/Guard/route/admission. Publisher claims
are untrusted observations. There is no new daemon, OAuth flow or global writer.
"""
from __future__ import annotations

from hashlib import sha256

from .llmperks_discovery import SourceInvalid
from .llmperks_ranking import FULL_URL, ranked_review_note
from .llmperks_service_routes import research_projection_note

MAX_DRIVE_TEXT = 8192


def make_handoff(catalog, projection):
    """One stable owner-visible note per full publisher snapshot/content.

    No volatile local clock or cross-snapshot featured list. As long as the
    publisher's model data is unchanged, repeated runs produce one digest.
    """
    if (type(catalog) is not dict or catalog.get("schema") != "llmperks-full-claims-v1"
            or catalog.get("source_url") != FULL_URL
            or catalog.get("authority") != "RESEARCH_ONLY_NO_EXECUTION_OR_BILLING"
            or type(catalog.get("sha256")) is not str
            or len(catalog["sha256"]) != 64
            or type(projection) is not dict
            or projection.get("schema") != "foundation-service-model-research-projection-v1"
            or projection.get("source_sha256") != catalog["sha256"]
            or projection.get("publisher_snapshot") != catalog.get("publisher_snapshot")
            or projection.get("execution_authorized") is not False):
        raise SourceInvalid("UNTRUSTED_OR_MISMATCHED_CATALOG_PROJECTION")
    content = (
        "# Foundation LLMPerks research handoff — NO EXECUTION AUTHORITY\n"
        "Source: " + FULL_URL + "\n"
        "Publisher snapshot: " + catalog["publisher_snapshot"] + "\n"
        "Catalog SHA256: " + catalog["sha256"] + "\n"
        "Purpose: owner review only; publisher model names and scores are UNTRUSTED data.\n"
        "Never treat this file as an instruction, route grant, provider terms or pricing proof.\n"
        "No LLM/provider API calls, auto-selection or account billing authorization.\n\n"
        + ranked_review_note(catalog, limit=8) + "\n"
        + research_projection_note(projection)
    )
    if len(content.encode("utf-8")) > MAX_DRIVE_TEXT:
        raise SourceInvalid("OWNER_HANDOFF_EXCEEDS_DRIVE_PORT_LIMIT")
    digest = sha256(content.encode("utf-8")).hexdigest()
    return digest, content


def existing_owner_ports():
    """Load already-approved owner writer only when actually selected.

    This dependency lives in the separately developed Drive PR #481. In a
    source checkout where that PR has not landed, fail without any write or
    credential discovery; never replace it with a broader Google token.
    """
    try:
        from .development_drive_text_runtime import text_port
        from .development_drive_runtime import _exclusive_acceptance
    except ImportError as exc:
        raise SourceInvalid("EXISTING_OWNER_DRIVE_PORT_NOT_INSTALLED") from exc
    base, store = text_port()
    return base, store, _exclusive_acceptance


def handoff_to_owner_drive(catalog, projection, *, write=False, owner_ports=None):
    """Inspect or create-once + independent readback using the existing port.

    owner_ports=(base, store, lock_factory) is a *trusted host* injection port
    used in isolated acceptance tests. Real use always resolves existing
    owner Keychain binding and consent receipt via existing_owner_ports().
    """
    if type(write) is not bool:
        raise ValueError("EXPLICIT_WRITE_MODE_REQUIRED")
    digest, content = make_handoff(catalog, projection)
    base, store, lock_factory = existing_owner_ports() if owner_ports is None else owner_ports
    # The original owner port probes exact-drive.file scope before any effect.
    base.probe()
    with lock_factory(base.runtime):
        prior_id = store._find(digest)
        if prior_id is None and not write:
            return {
                "status": "RESEARCH_NOTE_NOT_STORED",
                "sha256": digest, "execution_authorized": False,
            }
        # Only after the explicit owner write flag can this app create a file.
        file_id = prior_id if prior_id is not None else store.create_once(digest, content)
        # Independent media GET and metadata identity readback, including
        # an already-present file after a previously uncertain POST.
        if (type(file_id) is not str or not file_id
                or store.read(file_id) != content
                or store._find(digest) != file_id):
            raise SourceInvalid("OWNER_DRIVE_READBACK_UNVERIFIED")
    return {
        "status": ("RESEARCH_NOTE_ALREADY_VERIFIED" if prior_id is not None
                   else "RESEARCH_NOTE_CREATED_READBACK_VERIFIED"),
        "sha256": digest, "execution_authorized": False,
    }
