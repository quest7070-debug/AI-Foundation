"""Legacy optional question-transport boundary, not a development owner.

Kandev was the original task/session lifecycle and External MCP transport
for this adapter. That historic assignment is superseded by current
SYSTEM_ROLE_BOUNDARIES: existing Foundation host/Guard/Harness owns admitted
development, and the owner's active workflow does not invoke Kandev.
This module only classifies a normalized pending question and binds a proposed
answer to the exact observed question generation before transport delivery.
No tool, scheduler, permission or approval can be derived from this module.
"""
from dataclasses import dataclass
from hashlib import sha256
import json
import re

_SECRET = re.compile(r"(?i)(password|passwd|passphrase|api[_ -]?key|secret|token|bearer|private[_ -]?key|パスワード|api(?:キー|鍵)|トークン|秘密鍵)")
_PRIVATE = re.compile(r"(?i)(private|personal|confidential|個人情報|秘密|機密|住所|電話|メール)")
_LATEST = re.compile(r"(?i)(latest|current|today|recent|最新版|最新|現在|今日)")
_AUTHORITY = re.compile(r"(?i)(approve|authorization|authority|payment|purchase|deploy|production|delete|irreversible|external effect|承認|権限|課金|購入|本番|削除|不可逆|外部作用)")


@dataclass(frozen=True)
class QuestionIdentity:
    pending_id: str
    task_id: str
    session_id: str
    digest: str


@dataclass(frozen=True)
class QuestionDecision:
    route: str
    identity: QuestionIdentity
    reason: str


def _stable_payload(bundle):
    return {
        "pending_id": str(bundle.get("pending_id", "")),
        "task_id": str(bundle.get("task_id", "")),
        "session_id": str(bundle.get("session_id", "")),
        "questions": [
            {
                "question_id": str(q.get("question_id", "")),
                "prompt": str(q.get("prompt", "")),
                "options": [
                    {"option_id": str(o.get("option_id", "")), "label": str(o.get("label", ""))}
                    for o in q.get("options", ())
                ],
            }
            for q in bundle.get("questions", ())
        ],
    }


def question_identity(bundle):
    payload = _stable_payload(bundle)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return QuestionIdentity(payload["pending_id"], payload["task_id"], payload["session_id"], sha256(raw.encode()).hexdigest())


def classify_question(bundle, *, canon_resolved=False, evidence_resolved=False):
    """Choose capability without invoking any model.

    Deterministic Canon/evidence resolution always wins.  Secret-bearing
    questions never cross an inference boundary.
    """
    ident = question_identity(bundle)
    # Option labels may themselves contain credential/private values. Never
    # classify only the prompt and then send sensitive choices to an LLM.
    texts = []
    for q in bundle.get("questions", ()):
        if not isinstance(q, dict):
            continue
        texts.append(str(q.get("prompt", "")))
        for option in q.get("options") or ():
            if isinstance(option, dict):
                texts.append(str(option.get("label", "")))
    text = "\n".join(texts)
    if canon_resolved or evidence_resolved:
        return QuestionDecision("DETERMINISTIC", ident, "canon_or_evidence")
    if _SECRET.search(text):
        return QuestionDecision("CREDENTIAL_BOUNDARY", ident, "raw_secret")
    if _AUTHORITY.search(text):
        return QuestionDecision("HUMAN_GATE", ident, "unresolved_authority")
    if _LATEST.search(text):
        return QuestionDecision("SEARCH", ident, "fresh_information")
    if _PRIVATE.search(text):
        return QuestionDecision("LOCAL", ident, "private_reasoning")
    return QuestionDecision("REASONING", ident, "ordinary_reasoning")


def revalidate_question(observed_identity, current_bundle):
    """Fail closed when the pending question was withdrawn/replaced/changed."""
    if current_bundle is None:
        return False
    return observed_identity == question_identity(current_bundle)


def answer_claim(observed_identity, current_bundle, answers):
    """Create the minimal idempotent correlation record for native MCP delivery."""
    if not revalidate_question(observed_identity, current_bundle):
        raise ValueError("STALE_QUESTION")
    normalized = tuple(
        (
            str(a.get("question_id", "")),
            tuple(str(x) for x in a.get("selected_options", ())),
            bool(a.get("custom_text")),
        )
        for a in answers
    )
    digest = sha256(repr((observed_identity.digest, normalized)).encode()).hexdigest()
    return {
        "pending_id": observed_identity.pending_id,
        "task_id": observed_identity.task_id,
        "session_id": observed_identity.session_id,
        "question_digest": observed_identity.digest,
        "answer_digest": digest,
    }


@dataclass(frozen=True)
class QuestionResolution:
    decision: QuestionDecision
    answer: object | None = None
    human_summary: str = ""
    human_detail: str = ""


class SemanticQuestionBridge:
    """Legacy question coordinator; does not select or launch an executor.

    Only host-bound callbacks may provide current Canon/evidence, capability
    execution and pending-question claims. The optional old transport is
    retained for compatibility, not active development admission.
    """

    def __init__(self, *, resolve_deterministic, execute_capability, current_question, deliver_answer):
        self.resolve_deterministic = resolve_deterministic
        self.execute_capability = execute_capability
        self.current_question = current_question
        self.deliver_answer = deliver_answer

    def resolve(self, bundle):
        deterministic = self.resolve_deterministic(bundle)
        if deterministic is not None:
            decision = classify_question(bundle, canon_resolved=True)
            return QuestionResolution(decision, deterministic)
        decision = classify_question(bundle)
        if decision.route == "CREDENTIAL_BOUNDARY":
            return QuestionResolution(
                decision, None,
                "資格情報の判断が必要です。",
                "生の秘密値はLLMへ渡しません。ネイティブ資格情報境界で存在・binding・利用可否だけを確認してください。",
            )
        if decision.route == "HUMAN_GATE":
            return QuestionResolution(
                decision, None,
                "人の権限判断が必要です。",
                "Canonと既存証拠だけでは一意に決められない権限・課金・本番・不可逆または外部作用の判断です。",
            )
        return QuestionResolution(decision, self.execute_capability(decision.route, bundle))

    def deliver(self, resolution, answers):
        if resolution.answer is None and resolution.decision.route in {"HUMAN_GATE", "CREDENTIAL_BOUNDARY"}:
            raise ValueError("HUMAN_INPUT_REQUIRED")
        current = self.current_question(resolution.decision.identity.pending_id)
        claim = answer_claim(resolution.decision.identity, current, answers)
        result = self.deliver_answer(claim, answers)
        return {"claim": claim, "result": result}
