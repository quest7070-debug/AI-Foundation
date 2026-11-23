from ai_foundation.question_bridge import answer_claim, classify_question, question_identity, revalidate_question


def bundle(prompt="Choose direction", pending="p", session="s"):
    return {"pending_id":pending,"task_id":"t","session_id":session,"questions":[{"question_id":"q","prompt":prompt,"options":[{"option_id":"a","label":"A"},{"option_id":"b","label":"B"}]}]}


def test_canon_evidence_resolves_before_models():
    assert classify_question(bundle("production deploy?"), canon_resolved=True).route=="DETERMINISTIC"


def test_secret_never_routes_to_llm():
    assert classify_question(bundle("Which API key should I use?")).route=="CREDENTIAL_BOUNDARY"


def test_unresolved_authority_goes_human():
    assert classify_question(bundle("Approve production deploy?")).route=="HUMAN_GATE"


def test_latest_information_uses_search():
    assert classify_question(bundle("What is the latest API spec?")).route=="SEARCH"


def test_private_reasoning_is_local_only():
    assert classify_question(bundle("Reason about this confidential design")).route=="LOCAL"


def test_ordinary_reasoning_reuses_existing_router():
    assert classify_question(bundle()).route=="REASONING"


def test_stale_or_replaced_generation_fails_closed():
    first=bundle(); ident=question_identity(first)
    assert revalidate_question(ident,first)
    assert not revalidate_question(ident,bundle(pending="new"))
    assert not revalidate_question(ident,None)


def test_answer_claim_is_correlated_and_idempotent_without_raw_answer():
    b=bundle(); ident=question_identity(b); answers=[{"question_id":"q","selected_options":["a"],"custom_text":""}]
    a=answer_claim(ident,b,answers); again=answer_claim(ident,b,answers)
    assert a==again
    assert a["pending_id"]=="p" and a["session_id"]=="s"
    assert "answers" not in a and "custom_text" not in a


def test_question_change_rejected_before_delivery():
    b=bundle(); ident=question_identity(b)
    changed=bundle("Different question")
    try: answer_claim(ident,changed,[{"question_id":"q","selected_options":["a"]}])
    except ValueError as e: assert str(e)=="STALE_QUESTION"
    else: raise AssertionError("stale answer accepted")


def test_service_resolves_deterministically_before_capability():
    from ai_foundation.question_bridge import SemanticQuestionBridge
    calls=[]
    bridge=SemanticQuestionBridge(
        resolve_deterministic=lambda b:"A",
        execute_capability=lambda route,b:calls.append(route),
        current_question=lambda p:bundle(),
        deliver_answer=lambda claim,answers:{"claimed":True},
    )
    r=bridge.resolve(bundle("Approve production deploy?"))
    assert r.decision.route=="DETERMINISTIC" and r.answer=="A" and calls==[]


def test_service_human_gate_is_digestible_and_not_auto_delivered():
    from ai_foundation.question_bridge import SemanticQuestionBridge
    bridge=SemanticQuestionBridge(
        resolve_deterministic=lambda b:None,
        execute_capability=lambda route,b:"unused",
        current_question=lambda p:bundle("Approve production deploy?"),
        deliver_answer=lambda *a:(_ for _ in ()).throw(AssertionError("must not deliver")),
    )
    r=bridge.resolve(bundle("Approve production deploy?"))
    assert r.decision.route=="HUMAN_GATE" and r.human_summary and r.human_detail
    try: bridge.deliver(r,[])
    except ValueError as e: assert str(e)=="HUMAN_INPUT_REQUIRED"
    else: raise AssertionError("human gate auto-delivered")


def test_service_revalidates_immediately_before_native_delivery():
    from ai_foundation.question_bridge import SemanticQuestionBridge
    sent=[]
    original=bundle("What is the latest API spec?")
    bridge=SemanticQuestionBridge(
        resolve_deterministic=lambda b:None,
        execute_capability=lambda route,b:"answer",
        current_question=lambda p:original,
        deliver_answer=lambda claim,answers:sent.append((claim,answers)) or {"claimed":True},
    )
    r=bridge.resolve(original)
    out=bridge.deliver(r,[{"question_id":"q","selected_options":["a"]}])
    assert r.decision.route=="SEARCH" and out["result"]=={"claimed":True} and len(sent)==1


def test_service_never_delivers_answer_to_replaced_question():
    from ai_foundation.question_bridge import SemanticQuestionBridge
    original=bundle()
    bridge=SemanticQuestionBridge(
        resolve_deterministic=lambda b:None,
        execute_capability=lambda route,b:"answer",
        current_question=lambda p:bundle("replacement",pending="new"),
        deliver_answer=lambda *a:(_ for _ in ()).throw(AssertionError("must not deliver")),
    )
    r=bridge.resolve(original)
    try: bridge.deliver(r,[{"question_id":"q","selected_options":["a"]}])
    except ValueError as e: assert str(e)=="STALE_QUESTION"
    else: raise AssertionError("stale question delivered")


def test_sensitive_option_label_is_credential_boundary():
    b=bundle("Choose integration mode")
    b["questions"][0]["options"][0]["label"]="API key: sk-example-secret"
    assert classify_question(b).route=="CREDENTIAL_BOUNDARY"


def test_personal_option_label_stays_local():
    b=bundle("Choose response")
    b["questions"][0]["options"][0]["label"]="private owner preference"
    assert classify_question(b).route=="LOCAL"
