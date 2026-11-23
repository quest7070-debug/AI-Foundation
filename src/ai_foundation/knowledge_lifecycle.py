"""KLM: source-owned, no-effect input semantics and reconciliation.

Pure bounded proposal logic. A source adapter is responsible for authenticating
owner, record revision and principal; this module cannot grant such authority.
It neither runs an LLM nor writes external source systems or durable jobs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
import re
import sqlite3
import time
from pathlib import Path

POLICY_VERSION = "klm-input-semantics/v1"
SYSTEMS = frozenset({"github", "gdrive", "humanmodel", "foundation_runtime", "chat", "other"})
KINDS = frozenset({"observation", "decision", "instruction", "outcome", "inference", "question", "quote"})
MODALITIES = frozenset({"assertion", "intention", "conditional", "hypothetical", "unknown"})
POLARITIES = frozenset({"positive", "negative", "unknown"})
PRIVACY = {"shareable": 0, "restricted": 1, "private": 2}
ROLES = frozenset({"canonical", "projection", "reference", "index", "audit"})
RELATIONS = frozenset({"supports", "contradicts", "supersedes", "refines", "depends_on",
                       "same_as_candidate", "derived_from", "preserves_goal", "changes_priority"})
DOMAINS = {
    "development_task": "github",
    "code_spec": "github",
    "personal_judgment": "humanmodel",
    "cross_project_task": "gdrive",
    "project_plan": "gdrive",
    "career_plan": "gdrive",
    "music_project": "gdrive",
    "runtime_observation": "foundation_runtime",
}
MAX_SOURCE_BYTES = 32768
MAX_SPAN_BYTES = 4096
MAX_ATOMS = 32
MAX_RECEIPTS = 50000  # Fail closed at bound, never silently purge provenance.
ID_MAX = 512
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _nonempty(value, limit=ID_MAX):
    if not isinstance(value, str) or not 0 < len(value.strip()) <= limit or "\x00" in value:
        raise ValueError("nonempty bounded source identity required")
    return value


def _iso_or_none(value):
    if value is None:
        return None
    _nonempty(value, 40)
    if len(value) < 10:
        raise ValueError("invalid ISO-8601 observation time")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise ValueError("invalid ISO-8601 observation time") from None
    return value


def _digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class SourcePointer:
    """One explicitly scoped source row/section/event; not an entire mutable sheet."""
    system: str
    resource_id: str
    record_id: str
    revision: str
    scope: str
    privacy: str
    observed_at: str | None = None
    actor_claim: str = "unknown"

    def __post_init__(self):
        if self.system not in SYSTEMS or self.privacy not in PRIVACY:
            raise ValueError("unsupported source or privacy")
        for x in (self.resource_id, self.record_id, self.revision, self.scope):
            _nonempty(x)
        if self.scope == "*" or self.record_id == "*":
            raise ValueError("wildcard identity forbidden")
        _nonempty(self.actor_claim, 256)
        _iso_or_none(self.observed_at)


@dataclass(frozen=True)
class Meaning:
    kind: str
    modality: str
    polarity: str
    subject: str
    predicate: str
    object: str
    condition: str | None = None
    speaker_claim: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None

    def __post_init__(self):
        if (self.kind not in KINDS or self.modality not in MODALITIES
                or self.polarity not in POLARITIES):
            raise ValueError("invalid semantic category")
        for value in (self.subject, self.predicate, self.object):
            _nonempty(value, 512)
        for value in (self.condition, self.speaker_claim):
            if value is not None:
                _nonempty(value, 512)
        _iso_or_none(self.valid_from)
        _iso_or_none(self.valid_until)
        if self.valid_from is not None and self.valid_until is not None:
            a = datetime.fromisoformat(self.valid_from.replace("Z", "+00:00"))
            b = datetime.fromisoformat(self.valid_until.replace("Z", "+00:00"))
            try:
                if a > b:
                    raise ValueError("inverted validity interval")
            except TypeError:
                raise ValueError("incompatible validity timezones") from None


@dataclass(frozen=True)
class SemanticAtom:
    atom_id: str
    source: SourcePointer
    source_sha256: str
    span_sha256: str
    byte_start: int
    byte_end: int
    meaning: Meaning
    semantic_status: str = "proposed"
    # Even when bytes match, external owner/revision/actor is not authenticated here.
    source_authentication: str = "UNVERIFIED_OWNER"
    execution_authority: bool = False

    def __post_init__(self):
        if (self.semantic_status != "proposed"
                or self.source_authentication != "UNVERIFIED_OWNER"
                or self.execution_authority is not False):
            raise ValueError("raw semantic atom cannot mint owner or execution authority")


def decompose_verified_span(source: SourcePointer, raw: bytes, *, source_sha256: str,
                            start: int, end: int, meaning: Meaning) -> SemanticAtom:
    """Bind *proposed* meaning to exact bytes; never certify attribution or approval."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_SOURCE_BYTES:
        raise ValueError("bounded original bytes required")
    if not isinstance(source_sha256, str) or HEX64.fullmatch(source_sha256) is None:
        raise ValueError("source receipt SHA256 required")
    if sha256(raw).hexdigest() != source_sha256:
        raise ValueError("source revision/content mismatch")
    if (type(start) is not int or type(end) is not int
            or not 0 <= start < end <= len(raw) or end - start > MAX_SPAN_BYTES):
        raise ValueError("invalid exact byte span")
    try:
        raw[start:end].decode("utf-8")
        raw[:start].decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("span splits UTF-8 codepoint") from None
    span_hash = sha256(raw[start:end]).hexdigest()
    identity = {
        "policy": POLICY_VERSION, "owner_system": source.system,
        "resource_id": source.resource_id, "record_id": source.record_id,
        "revision": source.revision, "scope": source.scope,
        "source_sha256": source_sha256, "start": start, "end": end,
        "span_sha256": span_hash,
        "meaning": meaning.__dict__,
    }
    return SemanticAtom(_digest(identity), source, source_sha256, span_hash,
                        start, end, meaning)


def decompose_batch(source, raw, *, source_sha256, proposals):
    if not isinstance(proposals, (list, tuple)) or len(proposals) > MAX_ATOMS:
        raise ValueError("bounded semantic proposal batch required")
    atoms = [decompose_verified_span(source, raw, source_sha256=source_sha256,
                                     start=start, end=end, meaning=meaning)
             for start, end, meaning in proposals]
    if len({a.atom_id for a in atoms}) != len(atoms):
        raise ValueError("duplicate atom in same proposal batch")
    return tuple(atoms)


@dataclass(frozen=True)
class RelationProposal:
    kind: str
    source_atom_id: str
    target_atom_id: str
    status: str = "proposed"

    def __post_init__(self):
        if self.kind not in RELATIONS or self.status != "proposed":
            raise ValueError("relations are untrusted until owner verified")
        for value in (self.source_atom_id, self.target_atom_id):
            if not isinstance(value, str) or HEX64.fullmatch(value) is None:
                raise ValueError("exact atom references required")
        if self.source_atom_id == self.target_atom_id:
            raise ValueError("self relation is not evidence")


def compare_atoms(before: SemanticAtom, after: SemanticAtom) -> str:
    """Conservative evidence relations; no meaning-equivalence or approval inference."""
    if before.atom_id == after.atom_id:
        return "EXACT_DUPLICATE"
    if (before.source.system, before.source.resource_id, before.source.record_id
            ) == (after.source.system, after.source.resource_id, after.source.record_id):
        if before.source.revision == after.source.revision:
            return "SOURCE_REVISION_CONFLICT"
        return "REVISION_CHANGE_REVIEW"
    a, b = before.meaning, after.meaning
    if (before.source.scope != after.source.scope
            or before.source.privacy != after.source.privacy):
        return "CROSS_SCOPE_REVIEW"
    if (a.subject, a.predicate, a.object) == (b.subject, b.predicate, b.object):
        if (a.condition, a.valid_from, a.valid_until, a.modality) != (
                b.condition, b.valid_from, b.valid_until, b.modality):
            return "CONDITION_OR_TIME_SCOPE_REVIEW"
        if a.polarity != b.polarity and "unknown" not in (a.polarity, b.polarity):
            return "POTENTIAL_CONTRADICTION"
        return "SAME_AS_CANDIDATE"
    return "NO_DETERMINISTIC_RELATION"


@dataclass(frozen=True)
class OwnerTarget:
    """Host-selected exact record target; this class does not authenticate its source."""
    system: str
    resource_id: str
    record_id: str
    expected_revision: str
    scope: str
    privacy_ceiling: str
    role: str

    def __post_init__(self):
        if self.system not in SYSTEMS or self.role not in ROLES or self.privacy_ceiling not in PRIVACY:
            raise ValueError("invalid owner target")
        for value in (self.resource_id, self.record_id, self.expected_revision, self.scope):
            _nonempty(value)
        if self.scope == "*":
            raise ValueError("wildcard destination scope")


@dataclass(frozen=True)
class PlacementPlan:
    atom_id: str
    domain: str
    target: OwnerTarget | None
    status: str
    reason: str
    effect_authorized: bool = False

    def __post_init__(self):
        if self.effect_authorized is not False:
            raise ValueError("no-effect KLM placement cannot grant an external action")


def plan_placement(atom: SemanticAtom, domain: str, target: OwnerTarget | None) -> PlacementPlan:
    """P0-P2 no-effect plan; any remote write remains with the owner + Guard."""
    expected = DOMAINS.get(domain)
    if expected is None:
        return PlacementPlan(atom.atom_id, domain, target, "NEEDS_OWNER_MAPPING",
                             "UNRECOGNIZED_DOMAIN")
    if target is None:
        return PlacementPlan(atom.atom_id, domain, target, "NEEDS_OWNER_BINDING",
                             "EXACT_TARGET_REVISION_REQUIRED")
    if target.role == "canonical" and target.system != expected:
        return PlacementPlan(atom.atom_id, domain, target, "BLOCKED", "WRONG_CANONICAL_OWNER")
    if target.scope != atom.source.scope:
        return PlacementPlan(atom.atom_id, domain, target, "BLOCKED", "PRIVACY_SCOPE_MISMATCH")
    if PRIVACY[atom.source.privacy] > PRIVACY[target.privacy_ceiling]:
        return PlacementPlan(atom.atom_id, domain, target, "BLOCKED", "PRIVACY_SCOPE_MISMATCH")
    if target.role == "canonical":
        if atom.source.system != target.system:
            return PlacementPlan(atom.atom_id, domain, target, "NEEDS_OWNER_REVIEW",
                                 "CROSS_OWNER_CANONICAL_PROMOTION_FORBIDDEN")
        if atom.source.resource_id != target.resource_id or atom.source.record_id != target.record_id:
            return PlacementPlan(atom.atom_id, domain, target, "NEEDS_OWNER_REVIEW",
                                 "CANONICAL_RECORD_ID_MISMATCH")
        if atom.source.revision != target.expected_revision:
            return PlacementPlan(atom.atom_id, domain, target, "BLOCKED",
                                 "REVISION_MISMATCH")
    if domain == "personal_judgment":
        # A chat or generated "decision" is never promoted as the owner's decision.
        if atom.source.system != "humanmodel" or atom.meaning.kind != "decision":
            return PlacementPlan(atom.atom_id, domain, target, "NEEDS_HUMAN_REVIEW",
                                 "OWNER_DECISION_NOT_VERIFIED")
    if atom.meaning.kind == "inference" and domain == "personal_judgment":
        return PlacementPlan(atom.atom_id, domain, target, "NEEDS_HUMAN_REVIEW",
                             "INFERENCE_NOT_OWNER_DECISION")
    return PlacementPlan(atom.atom_id, domain, target, "PROPOSED_NO_EFFECT",
                         "REQUIRES_OWNER_ADMISSION_AND_GUARD")


@dataclass(frozen=True)
class SourceEvent:
    source: SourcePointer
    source_sha256: str
    event_kind: str
    coverage: str  # COMPLETE, PARTIAL, DISCONNECTED, UNKNOWN
    def __post_init__(self):
        _nonempty(self.event_kind, 128)
        if not isinstance(self.source_sha256, str) or HEX64.fullmatch(self.source_sha256) is None:
            raise ValueError("source event requires exact hash")
        if self.coverage not in {"COMPLETE", "PARTIAL", "DISCONNECTED", "UNKNOWN"}:
            raise ValueError("explicit source coverage required")

    @property
    def event_key(self):
        return _digest((self.source.system, self.source.resource_id, self.source.record_id,
                        self.source.revision, self.event_kind, self.source.scope))


@dataclass(frozen=True)
class AuditFinding:
    kind: str
    source_key: str
    detail: str


def audit_readonly(expected: tuple[SourceEvent, ...],
                   observed: tuple[SourceEvent, ...],
                   *, inventory_complete: bool) -> tuple[AuditFinding, ...]:
    """Compare exact identities/versions; incomplete scan can never assert absence."""
    if len(expected) > 1000 or len(observed) > 1000:
        raise ValueError("bounded audit window required")
    findings = []
    if not inventory_complete or any(e.coverage != "COMPLETE" for e in observed):
        findings.append(AuditFinding("UNKNOWN_COVERAGE", "inventory",
                                     "pagination/owner coverage unverified"))
    current = {}
    ambiguous = set()
    for e in observed:
        k = (e.source.system, e.source.resource_id, e.source.record_id, e.source.scope)
        previous = current.get(k)
        if previous is not None:
            # A current inventory must not silently select the last receipt.
            # Same record with different revision, bytes or privacy requires
            # owner review irrespective of pagination/observation order.
            conflict = (previous.source.revision != e.source.revision
                        or previous.source_sha256 != e.source_sha256)
            privacy = previous.source.privacy != e.source.privacy
            if k not in ambiguous and (conflict or privacy):
                findings.append(AuditFinding(
                    "PRIVACY_SCOPE_MISMATCH" if privacy else "OWNER_CONFLICT",
                    _digest(k), "conflicting observed source identities"))
                ambiguous.add(k)
            continue
        current[k] = e
    for prior in expected:
        k = (prior.source.system, prior.source.resource_id, prior.source.record_id, prior.source.scope)
        if k in ambiguous:
            # Contradictory current receipts cannot certify any single revision.
            continue
        now = current.get(k)
        if now is None:
            if inventory_complete and all(x.coverage == "COMPLETE" for x in observed):
                findings.append(AuditFinding("MISSING_SOURCE", prior.event_key,
                                             "complete owner scan omitted prior record"))
            continue
        if prior.source.revision != now.source.revision:
            findings.append(AuditFinding("REVISION_MISMATCH", prior.event_key,
                                         "source owner revision changed"))
        elif prior.source_sha256 != now.source_sha256:
            findings.append(AuditFinding("OWNER_CONFLICT", prior.event_key,
                                         "same source revision has changed content"))
        if prior.source.privacy != now.source.privacy:
            findings.append(AuditFinding("PRIVACY_SCOPE_MISMATCH", prior.event_key,
                                         "privacy ceiling changed"))
    return tuple(findings)


class ReadonlyReceiptJournal:
    """P0/P2 local link+receipt journal; NOT a work queue, owner DB or grant ledger."""
    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise PermissionError("symlinked KLM receipt path")
        if not self.path.parent.is_dir():
            raise FileNotFoundError("existing approved journal directory required")
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute("PRAGMA busy_timeout=5000")
            db.execute("""CREATE TABLE IF NOT EXISTS klm_observations (
                event_key TEXT PRIMARY KEY, system TEXT NOT NULL,
                resource_id TEXT NOT NULL, record_id TEXT NOT NULL,
                revision TEXT NOT NULL, scope TEXT NOT NULL,
                source_sha256 TEXT NOT NULL, coverage TEXT NOT NULL,
                policy TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS klm_plans (
                plan_key TEXT PRIMARY KEY, atom_id TEXT NOT NULL,
                domain TEXT NOT NULL, target_system TEXT NOT NULL,
                target_resource TEXT NOT NULL, target_record TEXT NOT NULL,
                expected_revision TEXT NOT NULL, role TEXT NOT NULL,
                status TEXT NOT NULL, reason TEXT NOT NULL,
                policy TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS klm_atoms (
                atom_id TEXT PRIMARY KEY, system TEXT NOT NULL,
                resource_id TEXT NOT NULL, record_id TEXT NOT NULL,
                revision TEXT NOT NULL, scope TEXT NOT NULL, privacy TEXT NOT NULL,
                source_sha256 TEXT NOT NULL, span_sha256 TEXT NOT NULL,
                byte_start INTEGER NOT NULL, byte_end INTEGER NOT NULL,
                meaning_sha256 TEXT NOT NULL, policy TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS klm_relations (
                relation_key TEXT PRIMARY KEY,
                source_atom_id TEXT NOT NULL REFERENCES klm_atoms(atom_id),
                target_atom_id TEXT NOT NULL REFERENCES klm_atoms(atom_id),
                kind TEXT NOT NULL, status TEXT NOT NULL, policy TEXT NOT NULL)""")
            # Derived fingerprints only: the source remains the owner of text.
            db.execute("""CREATE TABLE IF NOT EXISTS klm_atom_features (
                atom_id TEXT PRIMARY KEY REFERENCES klm_atoms(atom_id),
                subject TEXT NOT NULL, predicate TEXT NOT NULL, object TEXT NOT NULL,
                qualifiers TEXT NOT NULL, polarity TEXT NOT NULL, kind TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS klm_feature_subject ON klm_atom_features(subject,predicate)")
            db.execute("CREATE INDEX IF NOT EXISTS klm_atom_source ON klm_atoms(system,resource_id,record_id,scope,privacy)")
            db.execute("""CREATE TABLE IF NOT EXISTS klm_relation_reviews (
                review_key TEXT PRIMARY KEY, before_id TEXT NOT NULL,
                after_id TEXT NOT NULL, reason TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status='UNRESOLVED'), policy TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS klm_relation_dispositions (
                review_key TEXT PRIMARY KEY REFERENCES klm_relation_reviews(review_key),
                intent_sha256 TEXT NOT NULL, decision TEXT NOT NULL CHECK(decision IN ('ACCEPT','REJECT')),
                relation_kind TEXT NOT NULL, run_sha256 TEXT NOT NULL, canon_revision TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS klm_placement_candidates (
                atom_id TEXT NOT NULL, domain TEXT NOT NULL, owner TEXT,
                status TEXT NOT NULL, PRIMARY KEY(atom_id,domain))""")

    def record_event(self, event: SourceEvent) -> str:
        """Exact replay is silent; conflicting reused identity fails closed."""
        s = event.source
        with sqlite3.connect(self.path, timeout=5) as db:
            # Serialize read → exact replay / capacity check → insert. Without
            # BEGIN IMMEDIATE concurrent producers can exceed a bounded journal.
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT source_sha256,coverage FROM klm_observations WHERE event_key=?",
                (event.event_key,)).fetchone()
            if row is not None:
                if row != (event.source_sha256, event.coverage):
                    raise ValueError("same event key has conflicting source receipt")
                return "ALREADY_RECORDED"
            if db.execute("SELECT COUNT(*) FROM klm_observations").fetchone()[0] >= MAX_RECEIPTS:
                raise RuntimeError("KLM receipt capacity bound reached: operator review required")
            db.execute("""INSERT INTO klm_observations VALUES (?,?,?,?,?,?,?,?,?)""", (
                event.event_key, s.system, s.resource_id, s.record_id, s.revision,
                s.scope, event.source_sha256, event.coverage, POLICY_VERSION))
        return "RECORDED"

    def record_plan(self, plan: PlacementPlan) -> str:
        """Persist a no-effect proposal, never a grant or a side-effect receipt."""
        if plan.target is None or plan.effect_authorized:
            raise ValueError("only bounded no-effect target proposals may be journaled")
        t = plan.target
        key = _digest((plan.atom_id, plan.domain, t.system, t.resource_id,
                       t.record_id, t.expected_revision, t.role, POLICY_VERSION))
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM klm_atoms WHERE atom_id=?", (plan.atom_id,)).fetchone() is None:
                raise ValueError("placement references unregistered exact source atom")
            row = db.execute("SELECT status,reason FROM klm_plans WHERE plan_key=?", (key,)).fetchone()
            if row is not None:
                if row != (plan.status, plan.reason):
                    raise ValueError("plan identity reused with conflicting result")
                return "ALREADY_RECORDED"
            if db.execute("SELECT COUNT(*) FROM klm_plans").fetchone()[0] >= MAX_RECEIPTS:
                raise RuntimeError("KLM placement receipt capacity bound reached")
            db.execute("INSERT INTO klm_plans VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                key, plan.atom_id, plan.domain, t.system, t.resource_id, t.record_id,
                t.expected_revision, t.role, plan.status, plan.reason, POLICY_VERSION))
        return "RECORDED"


    def record_atom(self, atom: SemanticAtom) -> str:
        """Remember only exact source/span/semantic hashes: no private fact text."""
        if not isinstance(atom, SemanticAtom):
            raise TypeError("host-constructed proposal atom required")
        src = atom.source
        identity = {
            "policy": POLICY_VERSION, "owner_system": src.system,
            "resource_id": src.resource_id, "record_id": src.record_id,
            "revision": src.revision, "scope": src.scope,
            "source_sha256": atom.source_sha256,
            "start": atom.byte_start, "end": atom.byte_end,
            "span_sha256": atom.span_sha256, "meaning": atom.meaning.__dict__,
        }
        if (atom.atom_id != _digest(identity)
                or HEX64.fullmatch(atom.source_sha256) is None
                or HEX64.fullmatch(atom.span_sha256) is None
                or type(atom.byte_start) is not int or type(atom.byte_end) is not int
                or not 0 <= atom.byte_start < atom.byte_end <= MAX_SOURCE_BYTES
                or atom.byte_end - atom.byte_start > MAX_SPAN_BYTES):
            raise ValueError("atom identity or byte receipt mismatch")
        values = (atom.atom_id, src.system, src.resource_id, src.record_id, src.revision,
                  src.scope, src.privacy, atom.source_sha256, atom.span_sha256,
                  atom.byte_start, atom.byte_end, _digest(atom.meaning.__dict__), POLICY_VERSION)
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM klm_atoms WHERE atom_id=?", (atom.atom_id,)).fetchone()
            if old is not None:
                if old != values:
                    raise ValueError("atom ID reused with conflicting source metadata")
            elif db.execute("SELECT COUNT(*) FROM klm_atoms").fetchone()[0] >= MAX_RECEIPTS:
                raise RuntimeError("KLM atom index capacity reached")
            else:
                db.execute("INSERT INTO klm_atoms VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
            m = atom.meaning
            features = (atom.atom_id, _digest(m.subject), _digest(m.predicate),
                        _digest(m.object), _digest((m.condition, m.valid_from,
                        m.valid_until, m.modality, m.speaker_claim)), m.polarity, m.kind)
            previous = db.execute("SELECT * FROM klm_atom_features WHERE atom_id=?", (atom.atom_id,)).fetchone()
            if previous is not None and previous != features:
                raise ValueError("semantic feature identity conflict")
            db.execute("INSERT OR IGNORE INTO klm_atom_features VALUES (?,?,?,?,?,?,?)", features)
        return "ALREADY_RECORDED" if old is not None else "RECORDED"

    def record_relation(self, relation: RelationProposal) -> str:
        """Untrusted cross-atom link; no automatic conflict resolution or permission."""
        if not isinstance(relation, RelationProposal):
            raise TypeError("explicit relation proposal required")
        key = _digest((POLICY_VERSION, relation.source_atom_id,
                       relation.target_atom_id, relation.kind))
        with sqlite3.connect(self.path, timeout=5) as db:
            db.execute("BEGIN IMMEDIATE")
            ends = []
            for aid in (relation.source_atom_id, relation.target_atom_id):
                row = db.execute("SELECT scope,privacy FROM klm_atoms WHERE atom_id=?", (aid,)).fetchone()
                if row is None:
                    raise ValueError("relation references unregistered exact source atom")
                ends.append(row)
            if ends[0] != ends[1]:
                raise PermissionError("cross-scope/privacy relation requires owner review")
            old = db.execute("SELECT source_atom_id,target_atom_id,kind,status,policy "
                             "FROM klm_relations WHERE relation_key=?", (key,)).fetchone()
            values = (relation.source_atom_id, relation.target_atom_id,
                      relation.kind, relation.status, POLICY_VERSION)
            if old is not None:
                # Replaying an identical untrusted proposal cannot downgrade
                # an independently approved relation or make replay an error.
                reviewed = (*values[:3], "owner_verified", values[4])
                if old not in (values, reviewed):
                    raise ValueError("relation key reused with changed meaning")
                return "ALREADY_RECORDED"
            if db.execute("SELECT COUNT(*) FROM klm_relations").fetchone()[0] >= MAX_RECEIPTS:
                raise RuntimeError("KLM relation index capacity reached")
            db.execute("INSERT INTO klm_relations VALUES (?,?,?,?,?,?)", (key, *values))
        return "RECORDED"

    def reconcile_atom(self, atom_id, *, domain='unclassified'):
        """Reevaluate indexed neighbours only. All conclusions remain candidates.

        Old hash-only atoms cannot be reconstructed; audits expose that gap.
        Never compare private meanings across scope/privacy/owner boundaries.
        """
        if HEX64.fullmatch(atom_id) is None or domain not in {*DOMAINS, 'unclassified'}:
            raise ValueError('EXACT_ATOM_AND_DOMAIN_REQUIRED')
        with sqlite3.connect(self.path, timeout=5) as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('''SELECT a.*,f.subject,f.predicate,f.object,
                f.qualifiers,f.polarity,f.kind FROM klm_atoms a
                JOIN klm_atom_features f USING(atom_id) WHERE atom_id=?''', (atom_id,)).fetchone()
            if current is None:
                raise ValueError('ATOM_FEATURE_REHYDRATION_REQUIRED')
            # Two indexed candidate windows. UNION removes overlap; a bound is
            # a stop condition, never a silent certificate of complete recall.
            ids = db.execute('''SELECT atom_id FROM klm_atom_features
                WHERE subject=? AND predicate=? UNION
                SELECT atom_id FROM klm_atoms WHERE system=? AND resource_id=?
                AND record_id=? UNION
                SELECT r.source_atom_id FROM klm_relations r JOIN klm_atoms a
                ON a.atom_id=r.target_atom_id WHERE r.kind='depends_on'
                AND a.system=? AND a.resource_id=? AND a.record_id=?
                LIMIT 1001''', (current['subject'], current['predicate'],
                current['system'], current['resource_id'], current['record_id'],
                current['system'], current['resource_id'], current['record_id'])).fetchall()
            if len(ids) > 1000:
                return {'status': 'CANDIDATE_WINDOW_EXCEEDED', 'evaluated': 0}
            count = boundary = legacy = 0
            for candidate in ids:
                if candidate[0] == atom_id:
                    continue
                prior = db.execute('''SELECT a.*,f.subject,f.predicate,f.object,
                    f.qualifiers,f.polarity,f.kind FROM klm_atoms a
                    LEFT JOIN klm_atom_features f USING(atom_id) WHERE atom_id=?''', candidate).fetchone()
                if any(prior[k] != current[k] for k in ('scope', 'privacy', 'system')):
                    boundary += 1
                    continue
                if prior['subject'] is None:
                    legacy += 1
                    continue
                same_record = all(prior[k] == current[k] for k in ('system','resource_id','record_id'))
                depends = db.execute('''SELECT 1 FROM klm_relations r JOIN klm_atoms a
                    ON a.atom_id=r.target_atom_id WHERE r.source_atom_id=?
                    AND r.kind='depends_on' AND a.system=? AND a.resource_id=? AND a.record_id=?''',
                    (candidate[0],current['system'],current['resource_id'],current['record_id'])).fetchone()
                if depends:
                    reason = 'DEPENDENCY_REVIEW'
                elif same_record:
                    reason = ('REVISION_OR_REINTERPRETATION_REVIEW' if prior['revision'] != current['revision']
                              else 'SAME_REVISION_INTERPRETATION_REVIEW')
                elif prior['qualifiers'] != current['qualifiers']:
                    reason = 'CONDITION_TIME_OR_ATTRIBUTION_REVIEW'
                elif prior['polarity'] != current['polarity']:
                    # A negation is not hidden by an object wording difference.
                    # Still a review candidate, never a certified contradiction.
                    reason = ('POTENTIAL_CONTRADICTION' if 'unknown' not in
                              (prior['polarity'], current['polarity']) else 'UNKNOWN_POLARITY_REVIEW')
                elif prior['object'] != current['object']:
                    reason = 'UNRESOLVED_VALUE_DIFFERENCE'
                elif prior['kind'] != current['kind']:
                    reason = 'POTENTIAL_SUPPORT_KIND_REVIEW'
                else:
                    reason = 'SAME_INFORMATION_CANDIDATE'
                key = _digest((sorted((candidate[0], atom_id)), reason, POLICY_VERSION))
                if not db.execute('SELECT 1 FROM klm_relation_reviews WHERE review_key=?', (key,)).fetchone():
                    if db.execute('SELECT COUNT(*) FROM klm_relation_reviews').fetchone()[0] >= MAX_RECEIPTS:
                        raise RuntimeError('RELATION_REVIEW_CAPACITY_REACHED')
                    db.execute('INSERT INTO klm_relation_reviews VALUES(?,?,?,?,?,?)',
                               (key, candidate[0], atom_id, reason, 'UNRESOLVED', POLICY_VERSION))
                count += 1
            owner = DOMAINS.get(domain)
            db.execute('INSERT OR IGNORE INTO klm_placement_candidates VALUES(?,?,?,?)',
                       (atom_id, domain, owner, 'NEEDS_OWNER_BINDING' if owner else 'NEEDS_OWNER_MAPPING'))
            return {'status': 'PROPOSED_NO_EFFECT', 'evaluated': count,
                    'boundary_reviews': boundary, 'legacy_features_missing': legacy,
                    'placement': 'NEEDS_OWNER_BINDING' if owner else 'NEEDS_OWNER_MAPPING'}

    def audit_due(self, work, *, now=None):
        """Daily/ISO-week/calendar-month receipts in existing Durable Work.

        Deterministic local checks only. Interrupted RUNNING claims are reported,
        never reset while their previous process might still be alive.
        """
        from datetime import timezone
        from .orchestration import WorkStatus
        now = time.time() if now is None else now
        dt = datetime.fromtimestamp(now, timezone.utc)
        periods = (('daily', dt.strftime('%Y-%m-%d')),
                   ('weekly', dt.strftime('%G-W%V')), ('monthly', dt.strftime('%Y-%m')))
        result = {}
        for cadence, period in periods:
            job = 'klm-audit:' + cadence + ':' + period
            work.ensure(job, ['audit-derived-receipts'])
            step = work.load(job)[0]
            if step.status is WorkStatus.VERIFIED:
                result[cadence] = 'ALREADY_VERIFIED'
                continue
            if step.status is WorkStatus.RUNNING:
                result[cadence] = 'RECONCILE_REQUIRED'
                continue
            if not work.claim_not_running(job, 0):
                result[cadence] = 'CLAIM_UNAVAILABLE'
                continue
            try:
                with sqlite3.connect(self.path, timeout=5) as db:
                    missing = db.execute('''SELECT COUNT(*) FROM klm_atoms a
                        LEFT JOIN klm_atom_features f USING(atom_id) WHERE f.atom_id IS NULL''').fetchone()[0]
                    orphans = db.execute('''SELECT COUNT(*) FROM klm_relations r
                        LEFT JOIN klm_atoms a ON a.atom_id=r.source_atom_id
                        LEFT JOIN klm_atoms b ON b.atom_id=r.target_atom_id
                        WHERE a.atom_id IS NULL OR b.atom_id IS NULL''').fetchone()[0]
                    from .klm_relation_review import unresolved_review_filter
                    reviews = db.execute("SELECT COUNT(*) FROM klm_relation_reviews r WHERE "
                                         + unresolved_review_filter(db)).fetchone()[0]
                    # Versioned source atoms can coexist. Existing links to
                    # either revision must be re-reviewed, never promoted
                    # as a current owner relationship by this local audit.
                    relation_versions = db.execute("""
                        SELECT COUNT(*) FROM klm_relations r
                        JOIN klm_atoms a ON a.atom_id=r.source_atom_id
                        JOIN klm_atoms b ON b.atom_id=r.target_atom_id
                        WHERE EXISTS (
                            SELECT 1 FROM klm_atoms alt
                            WHERE alt.system=a.system
                              AND alt.resource_id=a.resource_id
                              AND alt.record_id=a.record_id
                              AND alt.scope=a.scope
                              AND alt.privacy=a.privacy
                              AND alt.revision<>a.revision)
                           OR EXISTS (
                            SELECT 1 FROM klm_atoms alt
                            WHERE alt.system=b.system
                              AND alt.resource_id=b.resource_id
                              AND alt.record_id=b.record_id
                              AND alt.scope=b.scope
                              AND alt.privacy=b.privacy
                              AND alt.revision<>b.revision)
                    """).fetchone()[0]
                    # Only inspect KLM intake when this journal shares its DB.
                    has_intake = db.execute("SELECT 1 FROM sqlite_master WHERE name='klm_drive_intake'").fetchone()
                    failed = db.execute("SELECT COUNT(*) FROM klm_drive_intake i JOIN work_steps w ON i.job_id=w.job_id WHERE w.status='FAILED'").fetchone()[0] if has_intake else 0
                receipt = {'missing_features': missing, 'orphan_relations': orphans,
                           'unresolved_relations': reviews,
                           'relation_revision_review_candidates': relation_versions,
                           'failed_intake': failed,
                           'source_inventory': 'OWNED_BY_NATIVE_DRIVE_CYCLE',
                           'model_calls': 0, 'external_writes': 0}
                work.set(job, 0, WorkStatus.VERIFIED, json.dumps(receipt, sort_keys=True))
                result[cadence] = receipt
            except Exception as exc:
                work.set(job, 0, WorkStatus.FAILED, type(exc).__name__)
                result[cadence] = 'FAILED'
        return result
