from dataclasses import replace

from ai_foundation.development_closeout import (
    CleanupDisposition,
    CleanupDomain,
    CleanupEntry,
    CloseoutRequest,
    CloseoutScope,
    CloseoutStatus,
    DeliveryEvidence,
    DeliveryKind,
    DeliveryNotificationStatus,
    ImprovementHandoffReceipt,
    RequestedAcceptance,
    TaskTerminalEvidence,
    TaskTerminalState,
    VerificationEvidence,
    WorkOutcome,
    assess_closeout,
)


def scope(**changes):
    value = CloseoutScope(
        task_id="paseo-task:42",
        original_request_id="request:42",
        owner_scope="owner-scope:42",
        repository="customer/project",
        improvement_target_repo="example/AI-Foundation",
        intent_revision="intent:3",
        source_revision="git:abc123",
        canon_revision="canon:def456",
        producer_ref="producer:agent",
        requested_acceptance=RequestedAcceptance.PULL_REQUEST,
    )
    return replace(value, **changes)


def verification(*, outcome=WorkOutcome.VERIFIED_CHANGE, **changes):
    value = VerificationEvidence(
        task_id="paseo-task:42",
        original_request_id="request:42",
        owner_scope="owner-scope:42",
        repository="customer/project",
        intent_revision="intent:3",
        source_revision="git:abc123",
        canon_revision="canon:def456",
        outcome=outcome,
        verifier_ref="reviewer:independent",
        evidence_ref="evidence:verification:42",
    )
    return replace(value, **changes)


def delivery(*, kind=DeliveryKind.PR_PRESENTED, **changes):
    value = DeliveryEvidence(
        task_id="paseo-task:42",
        original_request_id="request:42",
        owner_scope="owner-scope:42",
        repository="customer/project",
        intent_revision="intent:3",
        source_revision="git:abc123",
        canon_revision="canon:def456",
        kind=kind,
        notification_status=DeliveryNotificationStatus.DELIVERED,
        notification_ref="notification:42",
        result_query_ref=None,
        target_ref="https://github.com/example/repo/pull/42",
        evidence_refs=("evidence:pr:42", "evidence:tests:42"),
    )
    return replace(value, **changes)


def handoff(**changes):
    value = ImprovementHandoffReceipt(
        task_id="paseo-task:42",
        original_request_id="request:42",
        owner_scope="owner-scope:42",
        source_repository="customer/project",
        intent_revision="intent:3",
        source_revision="git:abc123",
        canon_revision="canon:def456",
        target_repo="example/AI-Foundation",
        target_revision="git:target789",
        semantic_index_revision="semantic-index:target789",
        receipt_ref="receipt:improvement-handoff:42",
        readback_ref="readback:improvement-handoff:42",
        accepted_by_target_owner=True,
        purpose_ref="canon:purpose",
        non_goals_ref="canon:non-goals",
        dependency_refs=("dependencies:target789",),
        acceptance_refs=("tests:target789",),
        constraint_refs=("constraints:target789",),
        failure_knowledge_refs=("failure-review:none-observed",),
        monitoring_refs=("monitoring:target789",),
        authority_refs=("authority:target789",),
        rollback_refs=("rollback:target789",),
    )
    return replace(value, **changes)




def terminal(*, state=TaskTerminalState.SETTLED, **changes):
    value = TaskTerminalEvidence(
        task_id="paseo-task:42",
        original_request_id="request:42",
        owner_scope="owner-scope:42",
        repository="customer/project",
        intent_revision="intent:3",
        source_revision="git:abc123",
        canon_revision="canon:def456",
        state=state,
        owner_ref="paseo:task-lifecycle",
        receipt_ref="receipt:paseo-terminal:42",
        readback_ref="readback:paseo-terminal:42",
    )
    return replace(value, **changes)


def cleanup_ledger():
    return tuple(
        CleanupEntry(
            task_id="paseo-task:42",
            original_request_id="request:42",
            owner_scope="owner-scope:42",
            repository="customer/project",
            intent_revision="intent:3",
            source_revision="git:abc123",
            canon_revision="canon:def456",
            domain=domain,
            owner_ref=f"owner:{domain.value}",
            disposition=CleanupDisposition.RETAINED,
            reason="No deletion required; retained state is still referenced or recoverable.",
            evidence_refs=(f"inventory:{domain.value}",),
            postcheck_ref=f"postcheck:{domain.value}",
        )
        for domain in CleanupDomain
    )


def request(**changes):
    value = CloseoutRequest(
        scope=scope(),
        task_terminal=terminal(),
        verification=verification(),
        delivery=delivery(),
        improvement_handoff=handoff(),
        cleanup_ledger=cleanup_ledger(),
    )
    return replace(value, **changes)


def blocker_codes(result):
    return {item.code for item in result.blockers}


def test_complete_closeout_requires_and_accepts_all_five_gates():
    result = assess_closeout(request())

    assert result.status is CloseoutStatus.READY_TO_CLOSE
    assert result.ready_to_close is True
    assert result.blockers == ()
    assert "evidence:verification:42" in result.evidence_refs
    assert "receipt:improvement-handoff:42" in result.evidence_refs
    assert len(result.evidence_refs) >= len(CleanupDomain)


def test_no_change_is_a_valid_terminal_result_without_creating_a_pr():
    result = assess_closeout(request(
        task_terminal=terminal(state=TaskTerminalState.NO_CHANGE),
        verification=verification(outcome=WorkOutcome.NO_CHANGE_VERIFIED),
        delivery=delivery(
            kind=DeliveryKind.NO_CHANGE_PRESENTED,
            notification_status=DeliveryNotificationStatus.SUPPRESSED_QUERYABLE,
            notification_ref=None,
            result_query_ref="queryable-result:42",
        ),
    ))

    assert result.status is CloseoutStatus.NO_CHANGE_READY
    assert result.ready_to_close is True


def test_missing_cleanup_domain_blocks_closeout():
    ledger = cleanup_ledger()[:-1]
    result = assess_closeout(request(cleanup_ledger=ledger))

    assert result.status is CloseoutStatus.BLOCKED
    assert "CLEANUP_DOMAIN_MISSING" in blocker_codes(result)


def test_duplicate_cleanup_domain_blocks_closeout():
    ledger = cleanup_ledger()
    result = assess_closeout(request(cleanup_ledger=ledger + (ledger[0],)))

    assert result.status is CloseoutStatus.BLOCKED
    assert "CLEANUP_DOMAIN_DUPLICATE" in blocker_codes(result)


def test_unresolved_cleanup_domain_blocks_even_with_evidence():
    ledger = list(cleanup_ledger())
    ledger[0] = replace(
        ledger[0],
        disposition=CleanupDisposition.UNRESOLVED,
        reason="Owner cannot yet prove whether the cache is still leased.",
    )
    result = assess_closeout(request(cleanup_ledger=tuple(ledger)))

    assert result.status is CloseoutStatus.BLOCKED
    assert "CLEANUP_UNRESOLVED" in blocker_codes(result)


def test_retained_recovery_data_is_not_mistaken_for_failed_cleanup():
    ledger = list(cleanup_ledger())
    ledger[0] = replace(
        ledger[0],
        disposition=CleanupDisposition.RETAINED,
        reason="Last-known-good recovery generation remains required.",
    )
    result = assess_closeout(request(cleanup_ledger=tuple(ledger)))

    assert result.ready_to_close is True


def test_pending_questions_approvals_effects_or_semantics_block_closeout():
    result = assess_closeout(request(scope=scope(
        pending_questions=("question:1",),
        pending_approvals=("approval:1",),
        unreconciled_effects=("effect:uncertain",),
        unresolved_semantics=("symbol:unmapped",),
    )))

    assert result.status is CloseoutStatus.BLOCKED
    assert "PENDING_WORK" in blocker_codes(result)


def test_failed_blocked_uncertain_or_cancelled_work_never_closes_as_success():
    for outcome in (
        WorkOutcome.FAILED,
        WorkOutcome.BLOCKED,
        WorkOutcome.UNCERTAIN,
        WorkOutcome.CANCELLED,
    ):
        result = assess_closeout(request(
            verification=verification(outcome=outcome),
        ))
        assert result.status is CloseoutStatus.BLOCKED
        assert "VERIFICATION_OUTCOME_NOT_SUCCESS" in blocker_codes(result)


def test_verification_must_be_independent_of_the_producer():
    result = assess_closeout(request(
        verification=verification(verifier_ref="producer:agent"),
    ))

    assert result.status is CloseoutStatus.BLOCKED
    assert "VERIFIER_NOT_INDEPENDENT" in blocker_codes(result)


def test_delivery_kind_must_match_requested_acceptance_exactly():
    result = assess_closeout(request(
        delivery=delivery(kind=DeliveryKind.MERGED_ACCEPTED),
    ))

    assert result.status is CloseoutStatus.BLOCKED
    assert "DELIVERY_KIND_MISMATCH" in blocker_codes(result)


def test_human_acceptance_is_required_only_when_the_task_contract_says_so():
    result = assess_closeout(request(scope=scope(
        requires_human_acceptance=True,
        human_acceptance_ref=None,
    )))

    assert result.status is CloseoutStatus.BLOCKED
    assert "HUMAN_ACCEPTANCE_MISSING" in blocker_codes(result)


def test_improvement_handoff_requires_target_owner_receipt_and_readback():
    result = assess_closeout(request(
        improvement_handoff=handoff(accepted_by_target_owner=False),
    ))

    assert result.status is CloseoutStatus.BLOCKED
    assert "IMPROVEMENT_HANDOFF_NOT_RECEIVED" in blocker_codes(result)


def test_improvement_handoff_requires_semantics_tests_constraints_and_rollback():
    result = assess_closeout(request(
        improvement_handoff=handoff(
            semantic_index_revision="",
            acceptance_refs=(),
            constraint_refs=(),
            rollback_refs=(),
        ),
    ))

    assert result.status is CloseoutStatus.BLOCKED
    assert "IMPROVEMENT_HANDOFF_EVIDENCE_INCOMPLETE" in blocker_codes(result)


def test_all_evidence_must_bind_to_the_exact_task_and_revision():
    result = assess_closeout(request(
        verification=verification(source_revision="git:stale"),
        delivery=delivery(intent_revision="intent:old"),
        improvement_handoff=handoff(canon_revision="canon:old"),
    ))

    assert result.status is CloseoutStatus.BLOCKED
    assert "EVIDENCE_IDENTITY_MISMATCH" in blocker_codes(result)


def test_cleanup_requires_owner_reason_evidence_and_postcheck():
    ledger = list(cleanup_ledger())
    ledger[0] = replace(
        ledger[0],
        owner_ref="",
        evidence_refs=(),
        postcheck_ref="",
    )
    result = assess_closeout(request(cleanup_ledger=tuple(ledger)))

    assert result.status is CloseoutStatus.BLOCKED
    assert {
        "CLEANUP_OWNER_MISSING",
        "CLEANUP_EVIDENCE_MISSING",
        "CLEANUP_POSTCHECK_MISSING",
    }.issubset(blocker_codes(result))


def test_improvement_handoff_cannot_register_a_different_repository():
    result = assess_closeout(request(
        improvement_handoff=handoff(target_repo="other/project"),
    ))

    assert result.status is CloseoutStatus.BLOCKED
    assert "IMPROVEMENT_HANDOFF_REPOSITORY_MISMATCH" in blocker_codes(result)


def test_invalid_enum_values_fail_closed():
    ledger = list(cleanup_ledger())
    ledger[0] = replace(ledger[0], disposition="UNRESOLVED")
    result = assess_closeout(request(
        scope=scope(requested_acceptance="PR"),
        cleanup_ledger=tuple(ledger),
    ))

    assert result.status is CloseoutStatus.BLOCKED
    assert "REQUESTED_ACCEPTANCE_INVALID" in blocker_codes(result)
    assert "CLEANUP_DISPOSITION_INVALID" in blocker_codes(result)


def test_source_evidence_cannot_be_reused_across_repositories():
    result = assess_closeout(request(
        delivery=delivery(repository="another/project"),
    ))

    assert result.status is CloseoutStatus.BLOCKED
    assert "EVIDENCE_REPOSITORY_MISMATCH" in blocker_codes(result)


def test_paseo_terminal_readback_is_required_and_must_be_successful():
    missing = assess_closeout(request(task_terminal=None))
    active = assess_closeout(request(
        task_terminal=terminal(state=TaskTerminalState.ACTIVE),
    ))

    assert missing.status is CloseoutStatus.BLOCKED
    assert "TASK_TERMINAL_READBACK_MISSING" in blocker_codes(missing)
    assert active.status is CloseoutStatus.BLOCKED
    assert "TASK_TERMINAL_STATE_MISMATCH" in blocker_codes(active)


def test_notification_failure_or_pending_state_blocks_closeout():
    for status in (
        DeliveryNotificationStatus.FAILED,
        DeliveryNotificationStatus.PENDING,
        DeliveryNotificationStatus.EXPIRED,
    ):
        result = assess_closeout(request(
            delivery=delivery(notification_status=status),
        ))
        assert result.status is CloseoutStatus.BLOCKED
        assert "NOTIFICATION_NOT_DELIVERED" in blocker_codes(result)


def test_no_change_notification_suppression_requires_queryable_result():
    result = assess_closeout(request(
        delivery=delivery(
            notification_status=DeliveryNotificationStatus.SUPPRESSED_QUERYABLE,
            notification_ref=None,
            result_query_ref=None,
        ),
    ))

    assert result.status is CloseoutStatus.BLOCKED
    assert "NOTIFICATION_SUPPRESSION_UNJUSTIFIED" in blocker_codes(result)


def test_human_acceptance_requires_acknowledged_notification_and_receipt():
    result = assess_closeout(request(
        scope=scope(
            requires_human_acceptance=True,
            human_acceptance_ref="human-acceptance:42",
        ),
        delivery=delivery(
            notification_status=DeliveryNotificationStatus.DELIVERED,
        ),
    ))

    assert result.status is CloseoutStatus.BLOCKED
    assert "HUMAN_DECISION_NOT_ACKNOWLEDGED" in blocker_codes(result)


def test_acknowledged_human_acceptance_can_complete_closeout():
    result = assess_closeout(request(
        scope=scope(
            requires_human_acceptance=True,
            human_acceptance_ref="human-acceptance:42",
        ),
        delivery=delivery(
            notification_status=DeliveryNotificationStatus.ACKNOWLEDGED,
        ),
    ))

    assert result.status is CloseoutStatus.READY_TO_CLOSE


def test_delivery_rejects_blank_evidence_reference_even_when_other_refs_exist():
    result = assess_closeout(request(
        delivery=delivery(evidence_refs=("evidence:pr:42", "   ")),
    ))
    assert result.status is CloseoutStatus.BLOCKED
    assert "DELIVERY_EVIDENCE_MISSING" in blocker_codes(result)


def test_unhashable_verification_outcome_fails_closed_without_exception():
    result = assess_closeout(request(
        verification=verification(outcome=["VERIFIED_CHANGE"]),
    ))
    assert result.status is CloseoutStatus.BLOCKED
    assert "VERIFICATION_OUTCOME_INVALID" in blocker_codes(result)


def test_unhashable_requested_acceptance_fails_closed_without_exception():
    result = assess_closeout(request(
        scope=scope(requested_acceptance=["PULL_REQUEST"]),
    ))
    assert result.status is CloseoutStatus.BLOCKED
    assert "REQUESTED_ACCEPTANCE_INVALID" in blocker_codes(result)


def test_scalar_delivery_evidence_reference_is_rejected():
    result = assess_closeout(request(
        delivery=delivery(evidence_refs="evidence:pr:42"),
    ))
    assert result.status is CloseoutStatus.BLOCKED
    assert "DELIVERY_EVIDENCE_MISSING" in blocker_codes(result)
    assert "e" not in result.evidence_refs


def test_handoff_reference_fields_reject_scalar_strings():
    result = assess_closeout(request(
        improvement_handoff=handoff(dependency_refs="dependency:one"),
    ))
    assert result.status is CloseoutStatus.BLOCKED
    assert "IMPROVEMENT_HANDOFF_EVIDENCE_INCOMPLETE" in blocker_codes(result)
    assert "d" not in result.evidence_refs


def test_cleanup_evidence_rejects_scalar_strings():
    ledger = list(cleanup_ledger())
    ledger[0] = replace(ledger[0], evidence_refs="evidence:cleanup")
    result = assess_closeout(request(cleanup_ledger=tuple(ledger)))
    assert result.status is CloseoutStatus.BLOCKED
    assert "CLEANUP_EVIDENCE_MISSING" in blocker_codes(result)
    assert "e" not in result.evidence_refs


def test_unknown_pending_work_collection_blocks_closeout():
    result = assess_closeout(request(scope=scope(pending_questions=None)))
    assert result.status is CloseoutStatus.BLOCKED
    assert "PENDING_WORK_INVALID" in blocker_codes(result)
