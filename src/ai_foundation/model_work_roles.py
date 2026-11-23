"""Host-owned division of local and external inference responsibilities.

This is a *task admission* policy, not a model-driven classifier or a second
router. It does not provide egress, filesystem, tool or spending authority.
Caller must be the trusted host, never a prompt, issue body or model output.
"""
from dataclasses import dataclass
from enum import Enum
import hashlib
import re


class ModelWorkRole(str, Enum):
    FOUNDATION_DEVELOPMENT = "FOUNDATION_DEVELOPMENT"
    LOCAL_DEVELOPMENT = "LOCAL_DEVELOPMENT"
    HUMAN_MODEL = "HUMAN_MODEL"
    SECRET_MANAGEMENT = "SECRET_MANAGEMENT"
    DATA_SENSITIVITY_REVIEW = "DATA_SENSITIVITY_REVIEW"
    FINAL_CODE_REVIEW = "FINAL_CODE_REVIEW"
    ERROR_RECOVERY = "ERROR_RECOVERY"
    PRIVATE_KLM = "PRIVATE_KLM"
    M1_ACCEPTANCE = "M1_ACCEPTANCE"
    PRIVATE_CONTEXT = "PRIVATE_CONTEXT"
    PUBLIC_ERROR_TRIAGE = "PUBLIC_ERROR_TRIAGE"
    PUBLIC_CODE_REVIEW = "PUBLIC_CODE_REVIEW"
    PUBLIC_FIXTURE_COMPARISON = "PUBLIC_FIXTURE_COMPARISON"
    PUBLIC_TEXT_ANALYSIS = "PUBLIC_TEXT_ANALYSIS"
    PUBLIC_SUMMARIZATION = "PUBLIC_SUMMARIZATION"
    PUBLIC_PLANNING = "PUBLIC_PLANNING"


LOCAL_ROLES = frozenset({
    ModelWorkRole.LOCAL_DEVELOPMENT, ModelWorkRole.HUMAN_MODEL,
    ModelWorkRole.SECRET_MANAGEMENT, ModelWorkRole.DATA_SENSITIVITY_REVIEW,
    ModelWorkRole.FINAL_CODE_REVIEW, ModelWorkRole.ERROR_RECOVERY,
    ModelWorkRole.PRIVATE_KLM, ModelWorkRole.M1_ACCEPTANCE,
    ModelWorkRole.PRIVATE_CONTEXT,
})
PUBLIC_ROLES = frozenset({
    ModelWorkRole.FOUNDATION_DEVELOPMENT,
    ModelWorkRole.PUBLIC_CODE_REVIEW,
    ModelWorkRole.PUBLIC_FIXTURE_COMPARISON,
    ModelWorkRole.PUBLIC_ERROR_TRIAGE,
    ModelWorkRole.PUBLIC_TEXT_ANALYSIS,
    ModelWorkRole.PUBLIC_SUMMARIZATION,
    ModelWorkRole.PUBLIC_PLANNING,
})
# Coarse defense in depth; it is not a substitute for host-side inspection.
_SENSITIVE = re.compile(
    r"(?i)(?:\bgsk_[A-Za-z0-9_-]{16,}\b|\bsk-[A-Za-z0-9_-]{16,}\b|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\b(?:api[_ -]?key|password|bearer)[=:]\s*\S+|"
    r"/Users/[^/\s]+/|/home/[^/\s]+/|"
    r"\bHumanModel\b|\bLOCAL_ONLY\b)"
)
MAX_PUBLIC_CHARS = 4096


@dataclass(frozen=True)
class ModelWorkContract:
    role: ModelWorkRole
    data_class: str = "LOCAL_ONLY"
    public_source: str = ""
    reviewed_sha256: str = ""
    host_public_reviewed: bool = False
    external_transfer_allowed: bool = False
    local_data_reviewed: bool = False
    local_data_verdict: str = "UNKNOWN"


@dataclass(frozen=True)
class RoleDecision:
    allowed: bool
    local_required: bool
    external_preferred: bool
    reason: str


def evaluate_model_work(contract, *, text, privacy_text=None):
    """Evaluate exact outbound text with the host's explicit role and provenance.

    HumanModel, secrets, final-code acceptance, incident/error recovery and
    data-sensitivity classification stay local. Routine Foundation coding is
    external-first only after trusted-host validation of a local data review
    for the exact outbound payload. Unknown/ambiguous remains local-only.
    """
    if not isinstance(contract, ModelWorkContract) or not isinstance(contract.role, ModelWorkRole):
        return RoleDecision(False, False, False, "ROLE_CONTRACT_REQUIRED")
    if contract.role in LOCAL_ROLES:
        return RoleDecision(True, True, False, "LOCAL_OWNED_WORK")
    if contract.role not in PUBLIC_ROLES:
        return RoleDecision(False, False, False, "ROLE_UNSUPPORTED")
    if (contract.data_class != "PUBLIC_NONSECRET" or
            contract.host_public_reviewed is not True or
            contract.external_transfer_allowed is not True or
            contract.local_data_reviewed is not True or
            contract.local_data_verdict != "PUBLIC_NONSECRET"):
        return RoleDecision(True, True, False, "LOCAL_FALLBACK_EGRESS_NOT_ATTESTED")
    if (type(text) is not str or not text or len(text) > MAX_PUBLIC_CHARS or
            privacy_text is not None and privacy_text != text):
        return RoleDecision(True, True, False, "LOCAL_FALLBACK_PAYLOAD_SCOPE_MISMATCH")
    if (type(contract.public_source) is not str or
            not 1 <= len(contract.public_source) <= 160 or
            not contract.public_source.strip() or
            type(contract.reviewed_sha256) is not str or
            contract.reviewed_sha256 != hashlib.sha256(text.encode("utf-8")).hexdigest()):
        return RoleDecision(True, True, False, "LOCAL_FALLBACK_PAYLOAD_UNVERIFIED")
    if _SENSITIVE.search(text):
        return RoleDecision(True, True, False, "LOCAL_FALLBACK_PRIVATE_CONTEXT")
    # Reviewed nonsecret work prefers pinned remote-local Strata when ONLINE and
    # capable. Other admitted free routes and M1 remain fallbacks; no paid route.
    return RoleDecision(True, False, True, "PUBLIC_STRATA_FIRST_WITH_ADMITTED_FALLBACK")


def public_payload_hash(text):
    """For the trusted host's exact-payload review record, not auto approval."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
