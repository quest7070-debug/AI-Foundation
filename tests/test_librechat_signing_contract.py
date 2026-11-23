import json
from ai_foundation.librechat_signing_contract import sign_serialized_body
from scripts.chat_gateway import _verified_attachment_headers

def test_final_serialized_body_contract_matches_gateway_v2():
 body=json.dumps({'model':'foundation-auto','messages':[{'role':'user','content':'x'}]},separators=(',',':')).encode()
 sig=sign_serialized_body('s','u',body,attachment_ids=('f1',),capability='CODE',scope='p',long_running=True,timestamp=100)
 h={'X-Foundation-Owner':'u','X-Foundation-Attachments':'["f1"]','X-Foundation-Capability':'CODE','X-Foundation-Scope':'p','X-Foundation-Long-Running':'1','X-Foundation-Attachment-Timestamp':'100','X-Foundation-Attachment-Signature':sig}
 assert _verified_attachment_headers(h,'s',body,100)['X-Foundation-Capability']=='CODE'
 assert _verified_attachment_headers(h,'s',body+b' ',100)=={}


def test_librechat_patch_forces_auxiliary_model_calls_to_chat_without_scopes_or_attachments():
 patch=__import__('pathlib').Path('deploy/librechat-v0.8.7-foundation-signing.patch').read_text()
 assert 'primaryModel:' in patch
 assert 'requestedModel !== intent.primaryModel' in patch
 assert 'const capability = auxiliary ? "CHAT"' in patch
 assert 'const scope = auxiliary ? ""' in patch
 assert 'ids: auxiliary ? [] : ids' in patch
 assert 'longRunning: auxiliary ? false' in patch


def test_foundation_auto_primary_uses_signed_daily_scope_while_auxiliary_stays_empty():
    patch=__import__('pathlib').Path('deploy/librechat-v0.8.7-foundation-signing.patch').read_text()
    assert '"foundation-auto": ["CHAT", "daily-default"]' in patch
    assert 'const scope = auxiliary ? ""' in patch
    assert 'ids: auxiliary ? [] : ids' in patch
    assert 'longRunning: auxiliary ? false' in patch


def test_librechat_patch_uses_normalized_foundation_identity_and_vision_mode():
    from pathlib import Path

    patch=Path(
        'deploy/librechat-v0.8.7-foundation-signing.patch'
    ).read_text()

    # initializeAgent establishes agent.endpoint before attachment authority
    # is captured. customEndpointConfig is resolved later by getProviderConfig,
    # so referencing it here would hit JavaScript TDZ on attachment requests.
    assert 'if (agent.endpoint === "Foundation")' in patch
    assert 'if (customEndpointConfig?.name === "Foundation")' not in patch

    assert (
        'new Set(["CHAT", "SEARCH", "CODE", "DATA", "FILES", "VISION"])'
        in patch
    )

    assert '"foundation-vision": ["VISION", ""]' in patch

    # Authority still comes only from post-lookup request attachments.
    assert (
        'req.__foundationAuthorizedAttachments = '
        '(primedRequestAttachments ?? [])'
        in patch
    )
