from .question_bridge import classify_question

def _validate_bundle(bundle):
    """Reject malformed local-peer input before Canon/HumanModel/Guard touches it.

    The current loopback Kandev ingress does not establish owner identity.
    It must not accept objects with coercible/duplicate question identities,
    arbitrary nested structures or non-string option labels.
    """
    if type(bundle) is not dict:
        raise ValueError('invalid question bundle')
    for key in ('pending_id', 'task_id', 'session_id'):
        value = bundle.get(key)
        if type(value) is not str or not 1 <= len(value) <= 128 or not value.strip():
            raise ValueError('invalid question identity')
    questions = bundle.get('questions')
    if type(questions) is not list or not 1 <= len(questions) <= 32:
        raise ValueError('invalid question list')
    seen_questions = set()
    for question in questions:
        if type(question) is not dict:
            raise ValueError('invalid question')
        qid = question.get('question_id')
        prompt = question.get('prompt')
        options = question.get('options')
        if (type(qid) is not str or not 1 <= len(qid) <= 128
                or not qid.strip() or qid in seen_questions
                or type(prompt) is not str or len(prompt) > 4096
                or type(options) is not list or len(options) > 64):
            raise ValueError('invalid question fields')
        seen_questions.add(qid)
        seen_options = set()
        for option in options:
            if type(option) is not dict:
                raise ValueError('invalid option')
            oid = option.get('option_id')
            label = option.get('label')
            if (type(oid) is not str or not 1 <= len(oid) <= 128
                    or not oid.strip() or oid in seen_options
                    or type(label) is not str or len(label) > 4096):
                raise ValueError('invalid option fields')
            seen_options.add(oid)


def resolve_ingress(bundle, deterministic_resolver=None, *, primary_review=None,
                    exception_requires_owner=False):
    """Policy-first question triage; identity and view binding are host-owned.

    `exception_requires_owner` is an injected host conclusion, NEVER read from
    the untrusted Kandev question bundle. Routine work does not query HumanModel.
    """
    _validate_bundle(bundle)
    if type(exception_requires_owner) is not bool:
        raise ValueError('host exception gate must be boolean')
    deterministic = deterministic_resolver(bundle) if deterministic_resolver else None
    decision=classify_question(bundle,canon_resolved=deterministic is not None)
    out={'route':decision.route,'reason':decision.reason,'question_digest':decision.identity.digest}
    if deterministic is not None:
        out['answer']=deterministic
    elif (decision.route == 'HUMAN_GATE' or
          (exception_requires_owner and decision.route in {'REASONING','LOCAL'})):
        if primary_review is None:
            # Caller cannot invent identity/approved views from question fields.
            out['route']='HUMAN_GATE'
            out['reason']='OWNER_REVIEW_BOUNDARY_UNAVAILABLE'
            out['requires_human']=True
        else:
            # Only a host-injected, authenticated owner-bound reviewer may use
            # this optional branch. The question cannot choose owner, View or Guard.
            review=primary_review.review(bundle)
            out['review_status']=review.status
            out['review_reason']=review.reason
            if review.status == 'RESOLVED_DELEGATED':
                out['route']='DETERMINISTIC'
                out['answer']=review.answer
            elif review.status == 'REVIEW_FAILED':
                out['route']='PRIMARY_REVIEW_FAILED'
                out['requires_attention']=True
            else:
                out['route']='HUMAN_GATE'
                out['requires_human']=True
    elif decision.route == 'CREDENTIAL_BOUNDARY':
        out['requires_human']=True
    else:
        out['requires_capability']=decision.route
    return out
