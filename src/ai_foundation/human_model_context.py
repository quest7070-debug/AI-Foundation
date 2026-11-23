"""Host-bound HumanModel retrieval. No personal store, inference, or write API."""
from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import sys
import types

PRIVACY_LEVELS = {'shareable': 0, 'restricted': 1, 'private': 2}


@dataclass(frozen=True)
class HumanModelBinding:
    owner_id: str
    root: str
    view_id: str
    scopes: tuple[str, ...]
    max_privacy: str

    def __post_init__(self):
        if (not isinstance(self.owner_id, str) or not self.owner_id or len(self.owner_id) > 256
                or not isinstance(self.view_id, str) or not self.view_id or len(self.view_id) > 128
                or not isinstance(self.root, str) or not Path(self.root).is_absolute()
                or '..' in Path(self.root).parts
                or self.max_privacy not in PRIVACY_LEVELS
                or not self.scopes or len(self.scopes) > 16
                or any(not isinstance(x, str) or not x.strip() or x == '*' or len(x) > 128 for x in self.scopes)
                or len(set(self.scopes)) != len(self.scopes)):
            raise ValueError('explicit host HumanModel binding required')

    @property
    def local_required(self):
        # No implicit cloud disclosure grant exists for restricted/private views.
        return self.max_privacy != 'shareable'


class HumanModelContext:
    def __init__(self, binding: HumanModelBinding, snapshot_reader, *, guard, run_id, search_backend=None):
        self.binding = binding
        self._reader = snapshot_reader
        self._guard = guard
        self._run_id = run_id
        self._search_backend = search_backend
        self.receipts = []  # request-scoped hashes only; no personal content cache
        self._page_anchors = {}  # request-local revision + next offset only

    @property
    def owner_id(self): return self.binding.owner_id

    @property
    def local_required(self): return self.binding.local_required

    @property
    def scopes(self): return self.binding.scopes

    @property
    def search_available(self): return True

    def reconstruction_evidence(self, owner_id, scope, question):
        """Select question-relevant evidence across the entire host-approved view.

        Page through the existing Guard-checked original reader, not a private
        index or new model. Return only bounded source records to the inference
        model. Never silently treat a page limit, omission or stale view as
        comprehensive coverage.
        """
        import re
        if owner_id != self.owner_id:
            raise PermissionError('HumanModel owner mismatch')
        if scope not in self.scopes:
            return {'status': 'UNAVAILABLE', 'reason': 'SCOPE_NOT_APPROVED'}
        if type(question) is not str or not question.strip() or len(question) > 2048:
            return {'status': 'UNAVAILABLE', 'reason': 'INVALID_AGENT_QUESTION'}

        # Exact lexical signals are deterministic and multilingual enough for
        # short Japanese bigrams; no persona or external embedding API is used.
        # Semantic quality is assessed separately against owner answers.
        words = set(re.findall(r'[a-z0-9]{3,}', question.casefold()))
        words.difference_update({
            'the', 'and', 'for', 'are', 'you', 'your', 'would', 'what',
            'when', 'where', 'which', 'could', 'should', 'about', 'this',
            'that', 'with', 'from', 'have', 'will', 'into', 'how',
        })
        japanese = re.findall(r'[\u3040-\u30ff\u3400-\u9fff]+', question)
        pairs = {s[i:i+2] for s in japanese for i in range(len(s)-1)}
        pairs.difference_update({'どう', 'です', 'ます', 'した', 'して', 'なら', 'なら',
                                '本人', '回答', '質問', '私な'})
        selected = []
        count = 0
        # A duplicated or malformed ID cannot become independent evidence
        # merely because the corpus spans multiple pages.
        seen_evidence_ids = set()
        uncertain_in_scope = 0
        offset = 0
        initial = None
        revision = None
        small_corpus_candidates = []
        while True:
            # The original read contract only admits offsets <= 4096.
            if offset > 4096:
                return {'status': 'UNAVAILABLE', 'reason': 'CORPUS_PAGINATION_LIMIT'}
            page = json.loads(self.read(owner_id, scope, offset=offset))
            if page.get('status') not in ('AVAILABLE', 'PARTIAL'):
                return {'status': 'UNAVAILABLE', 'reason': 'CORPUS_READ_UNAVAILABLE'}
            if page.get('omitted_record_ids'):
                return {'status': 'UNAVAILABLE', 'reason': 'CORPUS_RECORD_OMITTED'}
            if initial is None:
                initial = page['snapshot_sha256']
                revision = page['view_revision']
            elif page['view_revision'] != revision:
                # Snapshot hashes are per-page; revision pins the whole view.
                return {'status': 'UNAVAILABLE', 'reason': 'CORPUS_REVISION_CHANGED'}
            for record in page['records']:
                if not isinstance(record, dict):
                    return {'status': 'UNAVAILABLE', 'reason': 'CORPUS_IDENTITY_CONFLICT'}
                evidence_id = record.get('id')
                if (type(evidence_id) is not str or not evidence_id
                        or evidence_id in seen_evidence_ids):
                    return {'status': 'UNAVAILABLE', 'reason': 'CORPUS_IDENTITY_CONFLICT'}
                # Corrupted source payloads must fail closed before lexical
                # matching or forwarding evidence into an owner answer.
                if type(record.get('content')) is not str:
                    return {'status': 'UNAVAILABLE', 'reason': 'CORPUS_RECORD_INVALID'}
                seen_evidence_ids.add(evidence_id)
                count += 1
                # A byte-limited page can contain fewer than 32 records. Keep
                # all candidates for the small-corpus fallback across pages,
                # never just those on page one. Cap memory at 32 records.
                if len(small_corpus_candidates) < 32:
                    small_corpus_candidates.append(record)
                if record.get('disputed') in (1, True) or record.get('kind') == 'inference':
                    uncertain_in_scope += 1
                content = record['content'].casefold()
                score = sum(3 for term in words if term in content)
                score += sum(1 for term in pairs if term in content)
                if score:
                    selected.append((score, record))
            nxt = page.get('next_offset')
            if nxt is None:
                break
            if type(nxt) is not int or nxt <= offset or nxt > 4096:
                return {'status': 'UNAVAILABLE', 'reason': 'CORPUS_PAGINATION_LIMIT'}
            offset = nxt

        # A small corpus can be considered jointly even without exact keywords.
        # For larger corpora, abstain when relevance cannot be established.
        if not selected and count <= 32:
            selected = [(0, row) for row in small_corpus_candidates]
        if not selected:
            return {'status': 'UNAVAILABLE',
                    'reason': 'NO_RELEVANT_OWNER_EVIDENCE' if count else 'NO_OWNER_EVIDENCE'}

        # Retain highest-scoring sources; when score ties, the source reader
        # already sorts most-recent first. Keep enough room for synthesis.
        selected.sort(key=lambda pair: -pair[0])
        relevant_match_count = len(selected)
        records = []
        size = 0
        for _, row in selected[:12]:
            n = len(json.dumps(row, ensure_ascii=False).encode('utf-8'))
            if size + n > 24576:
                return {'status': 'UNAVAILABLE', 'reason': 'RELEVANT_EVIDENCE_TOO_LARGE'}
            records.append(row)
            size += n
        # Prove that the initial page still agrees with the same source
        # revision/receipt immediately before inference.
        check = json.loads(self.read(owner_id, scope))
        if (check.get('status') not in ('AVAILABLE', 'PARTIAL')
                or check.get('view_revision') != revision
                or check.get('snapshot_sha256') != initial):
            return {'status': 'UNAVAILABLE', 'reason': 'CORPUS_REVISION_CHANGED'}
        uncertain_selected = sum(
            row.get('disputed') in (1, True) or row.get('kind') == 'inference'
            for row in records)
        return {'status': 'AVAILABLE', 'records': records,
                'view_revision': revision, 'snapshot_sha256': initial,
                'scanned_records': count, 'retrieval_engine': 'approved-paged-literal-v1',
                'source_scan_complete': True,
                'coverage_complete': len(records) == count,
                'evidence_selection_complete': len(records) == count,
                'omitted_records': count - len(records),
                'omitted_uncertain_records': uncertain_in_scope - uncertain_selected,
                'relevant_match_count': relevant_match_count,
                'conflict_adjudication': 'NOT_PERFORMED'}

    def search(self, owner_id, scope, query):
        if not isinstance(query, str) or not query.strip() or len(query) > 512:
            return json.dumps({'status': 'UNAVAILABLE', 'reason': 'INVALID_SEARCH_QUERY'})
        # Reuse authenticated owner, scope, privacy and Guard admission.
        snapshot = json.loads(self.read(owner_id, scope))
        if snapshot.get('status') == 'PARTIAL':
            return json.dumps({'source': 'HumanModel', 'status': 'UNAVAILABLE',
                               'reason': 'COGNEE_REQUIRES_COMPLETE_BOUNDED_VIEW', 'execution_authority': False})
        if snapshot.get('status') != 'AVAILABLE': return json.dumps(snapshot, ensure_ascii=False)

        def current_view_unchanged():
            # The Guard, owner and current source are checked again immediately
            # before returning evidence, not only before searching. A stale
            # source result cannot be reclassified as the owner's current view.
            try:
                current = json.loads(self.read(owner_id, scope))
                return (current.get('status') == 'AVAILABLE'
                        and current.get('view_revision') == snapshot.get('view_revision')
                        and current.get('snapshot_sha256') == snapshot.get('snapshot_sha256'))
            except (PermissionError, ValueError, KeyError, TypeError):
                return False

        def source_changed():
            return json.dumps({'source': 'HumanModel', 'status': 'UNAVAILABLE',
                               'reason': 'SEARCH_SOURCE_CHANGED',
                               'execution_authority': False})

        # The approved view is at most 32 records / 32 KiB. A bounded
        # case-folded literal pass costs less than building any additional
        # index or starting the optional Cognee/9B worker.
        needle = query.strip().casefold()
        candidates = [row for row in snapshot['records']
                      if needle in str(row['id']).casefold()
                      or needle in str(row['content']).casefold()]
        if candidates:
            if len(candidates) > 10:
                return json.dumps({'source': 'HumanModel', 'status': 'UNAVAILABLE',
                                   'reason': 'SEARCH_RESULT_BOUND_EXCEEDED', 'execution_authority': False})
            if not current_view_unchanged():
                return source_changed()
            return json.dumps({**snapshot, 'records': candidates,
                               'retrieval_engine': 'approved-literal-v1',
                               'status': 'AVAILABLE',
                               'interpretations_are_personal_facts': False,
                               'requires_evidence_review': any(
                                   row.get('disputed') in (1, True)
                                   or row.get('kind') == 'inference'
                                   for row in candidates),
                               'retrieval_coverage': {
                                   'approved_source_count': len(snapshot['records']),
                                   'returned_source_count': len(candidates),
                                   'exhaustive_for_approved_view':
                                       len(candidates) == len(snapshot['records']),
                                   'conflict_adjudication': 'NOT_PERFORMED',
                               }}, ensure_ascii=False)
        if self._search_backend is None:
            if not current_view_unchanged():
                return source_changed()
            return json.dumps({**snapshot, 'records': [],
                               'retrieval_engine': 'approved-literal-v1',
                               'status': 'NO_MATCH',
                               'interpretations_are_personal_facts': False}, ensure_ascii=False)
        try:
            permitted = {row['id']: row for row in snapshot['records']}
            source = deepcopy({k: v for k, v in snapshot.items()
                               if k not in ('source', 'status', 'execution_authority')})
            source['_privacy_ceiling'] = self.binding.max_privacy
            result = self._search_backend(source, query)
            selected = []
            for row in result['records']:
                canonical = permitted[row['id']]
                if row != canonical: raise ValueError('Cognee source mismatch')
                selected.append(canonical)
            if len(selected) > 10 or len({r['id'] for r in selected}) != len(selected):
                raise ValueError('invalid Cognee result bound')
            returned = {r['id'] for r in selected}
            coverage = {
                'approved_source_count': len(permitted),
                'returned_source_count': len(selected),
                'unreturned_disputed_count': sum(
                    row.get('disputed') in (1, True)
                    for rid, row in permitted.items() if rid not in returned),
                'exhaustive_for_approved_view': len(returned) == len(permitted),
                'conflict_adjudication': 'NOT_PERFORMED',
            }
            if not current_view_unchanged():
                return source_changed()
            return json.dumps({**snapshot, 'records': selected, 'retrieval_engine': 'cognee==1.6.5',
                               'status': 'AVAILABLE' if selected else 'NO_MATCH',
                               'retrieval_coverage': coverage,
                               'interpretations_are_personal_facts': False}, ensure_ascii=False)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            return json.dumps({'source': 'HumanModel', 'status': 'UNAVAILABLE',
                               'reason': 'COGNEE_CURRENT_SEARCH_UNAVAILABLE', 'execution_authority': False})

    def read(self, owner_id, scope, *, offset=0):
        if owner_id != self.owner_id:
            raise PermissionError('HumanModel owner mismatch')
        if scope not in self.scopes:
            return json.dumps({'status': 'UNAVAILABLE', 'reason': 'SCOPE_NOT_APPROVED'})
        if type(offset) is not int or not 0 <= offset <= 4096:
            return json.dumps({'status': 'UNAVAILABLE', 'reason': 'PAGE_OUT_OF_RANGE'})
        from .core import CanonContract, Decision, TaskPlan
        revision = 'human-model-read-v1'
        target = 'human-model:' + hashlib.sha256((self.binding.view_id + '\0' + scope).encode()).hexdigest()
        decision = self._guard.preflight(TaskPlan(self._run_id, 'read', target,
                                                  canon_revision=revision),
                                         CanonContract('human-model-approved-view', revision))
        if decision not in (Decision.ALLOW, Decision.LOCAL_ONLY) or (decision is Decision.LOCAL_ONLY and not self.local_required):
            return json.dumps({'source': 'HumanModel', 'status': 'UNAVAILABLE',
                               'reason': 'GUARD_READ_NOT_AUTHORIZED', 'execution_authority': False})
        if offset == 0:
            self._page_anchors.pop(scope, None)
        if offset:
            anchor = self._page_anchors.get(scope)
            if anchor is None:
                return json.dumps({'source': 'HumanModel', 'status': 'UNAVAILABLE',
                                   'reason': 'PAGE_REVISION_NOT_PINNED', 'execution_authority': False})
            if offset != anchor[1]:
                return json.dumps({'source': 'HumanModel', 'status': 'UNAVAILABLE',
                                   'reason': 'PAGE_SEQUENCE_INVALID', 'execution_authority': False})
        try:
            snapshot = self._reader(self.binding.root, view_id=self.binding.view_id,
                                    scope=scope, max_privacy=self.binding.max_privacy,
                                    max_records=32, max_bytes=32768, offset=offset)
            if (type(snapshot) is not dict or snapshot.get('view_id') != self.binding.view_id
                    or snapshot.get('scope') != scope
                    or type(snapshot.get('view_revision')) is not int or snapshot['view_revision'] < 1
                    or not isinstance(snapshot.get('records'), list)):
                raise ValueError('invalid source snapshot')
            for row in snapshot['records']:
                if (type(row) is not dict or type(row.get('id')) is not str
                        or not row['id'] or type(row.get('content')) is not str
                        or row.get('scope') != scope or row.get('privacy') not in PRIVACY_LEVELS
                        or PRIVACY_LEVELS[row['privacy']] > PRIVACY_LEVELS[self.binding.max_privacy]):
                    raise PermissionError('source privacy/scope mismatch')
            if not isinstance(snapshot.get('snapshot_sha256'), str) or len(snapshot['snapshot_sha256']) != 64:
                raise ValueError('source receipt missing')
            next_offset = snapshot.get('next_offset')
            if snapshot.get('truncated') is True:
                if type(next_offset) is not int or not offset < next_offset <= 4096:
                    raise ValueError('invalid continuation cursor')
            elif next_offset is not None:
                raise ValueError('unexpected continuation cursor')
            if offset and snapshot['view_revision'] != anchor[0]:
                self._page_anchors.pop(scope, None)
                return json.dumps({'source': 'HumanModel', 'status': 'UNAVAILABLE',
                                   'reason': 'VIEW_REVISION_CHANGED_DURING_PAGINATION',
                                   'execution_authority': False})
            result = {**snapshot, 'source': 'HumanModel', 'status': 'PARTIAL' if snapshot.get('truncated') or snapshot.get('omitted_record_ids') else 'AVAILABLE',
                      'execution_authority': False}
            text = json.dumps(result, ensure_ascii=False)
            if len(text.encode()) > 36864:
                raise ValueError('source snapshot exceeds response bound')
        except (PermissionError, FileNotFoundError, OSError, ValueError, RuntimeError, sqlite3.Error, KeyError, TypeError):
            self._page_anchors.pop(scope, None)
            # Never expose private paths, SQL, raw source data or exception text.
            return json.dumps({'source': 'HumanModel', 'status': 'UNAVAILABLE',
                               'reason': 'APPROVED_CURRENT_VIEW_UNAVAILABLE', 'execution_authority': False})
        self.receipts.append({'view_revision': snapshot['view_revision'],
                              'snapshot_sha256': snapshot['snapshot_sha256']})
        del self.receipts[:-8]
        if snapshot.get('next_offset') is not None:
            self._page_anchors[scope] = (snapshot['view_revision'], snapshot['next_offset'])
        else:
            self._page_anchors.pop(scope, None)
        return text


def load_bindings(path):
    """Read an explicit host config; missing config leaves the feature disabled."""
    try:
        raw = Path(path).read_text(encoding='utf-8')
    except FileNotFoundError:
        return {}
    if len(raw.encode()) > 65536:
        raise ValueError('HumanModel host config too large')
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out: raise ValueError('duplicate HumanModel config key')
            out[key] = value
        return out
    row = json.loads(raw, object_pairs_hook=unique)
    if (not isinstance(row, dict) or set(row) != {'version', 'bindings'} or type(row['version']) is not int or row['version'] != 1
            or not isinstance(row['bindings'], list) or len(row['bindings']) > 32):
        raise ValueError('invalid HumanModel host config')
    bindings = {}
    for item in row['bindings']:
        if (not isinstance(item, dict) or set(item) != {'owner_id', 'root', 'view_id', 'scopes', 'max_privacy'}
                or not isinstance(item['scopes'], list)):
            raise ValueError('invalid HumanModel host binding')
        binding = HumanModelBinding(**{**item, 'scopes': tuple(item['scopes'])})
        if binding.owner_id in bindings: raise ValueError('duplicate HumanModel owner')
        bindings[binding.owner_id] = binding
    return bindings


def _source_reader(repository_root):
    """Load the existing HumanModel-owned adapter from this trusted repository.

    Its private package namespace avoids changing sys.path or shadowing unrelated
    top-level modules. The host, never the model/config, selects executable code.
    """
    directory = Path(repository_root).resolve() / 'experiments' / 'human_model'
    if not (directory / 'foundation_readonly.py').is_file():
        raise FileNotFoundError('HumanModel source adapter unavailable')
    name = '_foundation_humanmodel_' + hashlib.sha256(str(directory).encode()).hexdigest()[:16]
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = [str(directory)]
        sys.modules[name] = package
    return importlib.import_module(name + '.foundation_readonly').read_view_snapshot


def build_human_model_context(config_path, owner_id, *, repository_root, guard, run_id, collection_consent=None):
    binding = load_bindings(config_path).get(owner_id)
    if binding is None: return None
    reader = _source_reader(repository_root)
    if collection_consent is not None:
        # Only an authenticated host may supply this exact existing Guard
        # consent verifier. It gates newly admitted owner evidence at read time;
        # a model, JSON binding or old consent receipt cannot opt into it.
        from .human_model_collection_guard import GuardCollectionConsent
        if (type(collection_consent) is not GuardCollectionConsent
                or collection_consent.owner != owner_id
                or collection_consent.binding != binding
                or collection_consent.guard is not guard):
            raise PermissionError('trusted host collection consent required')
        original_reader = reader

        def reader(root, **kwargs):
            return original_reader(root,
                collection_current=collection_consent.active_digest, **kwargs)

    package = (original_reader if collection_consent is not None else reader).__module__.rsplit('.', 1)[0]
    try:
        backend = importlib.import_module(package + '.cognee_bridge').configured_search(
            binding.root, repository_root=repository_root)
    except ModuleNotFoundError:
        # Old releases without the optional source adapter retain direct reads.
        backend = None
    return HumanModelContext(binding, reader, guard=guard, run_id=run_id, search_backend=backend)
