"""Partial delivery cannot acknowledge another subscription's failed attempt."""
import json
from pathlib import Path

import pytest

from ai_foundation.push_dispatch import PushDispatch
from ai_foundation.webpush_transport import (
    SubscriptionStore, SubscriptionStoreCorrupt, WebPushConfig, WebPushTransport,
)


NOTICE = {'notices': [{'level': 4, 'kind': 'work', 'subject': 'job', 'status': 'WAITING_HUMAN'}]}
KEYED = {'key': 'work:job:WAITING_HUMAN', 'body': 'private payload is not persisted'}


def config(root):
    return WebPushConfig('private', 'public', 'mailto:x@example.invalid', root / 'subs.json')


def subscription(name, auth='test-auth'):
    return {'endpoint': 'https://push.example/' + name, 'keys': {'p256dh': 'test-key', 'auth': auth}}


def register(root, *names):
    store = SubscriptionStore(root / 'subs.json')
    for name in names:
        store.put(subscription(name))
    return store


def test_partial_failure_retries_only_missing_subscription_across_restart(tmp_path, monkeypatch):
    register(tmp_path, 'a', 'b')
    first = WebPushTransport(config(tmp_path))
    calls = []

    def send(sub, payload):
        calls.append(sub['endpoint'])
        if sub['endpoint'].endswith('/b'):
            raise OSError('temporary transport failure')

    monkeypatch.setattr(first, 'send', send)
    seen = tmp_path / 'seen.json'
    assert PushDispatch(first, seen).dispatch(NOTICE) == {'sent_notices': 0, 'failed_notices': 1}
    assert not seen.exists()
    restarted = WebPushTransport(config(tmp_path))
    monkeypatch.setattr(restarted, 'send', lambda sub, payload: calls.append(sub['endpoint']))
    assert PushDispatch(restarted, seen).dispatch(NOTICE) == {'sent_notices': 1, 'failed_notices': 0}
    assert calls == ['https://push.example/a', 'https://push.example/b', 'https://push.example/b']
    assert PushDispatch(restarted, seen).dispatch(NOTICE)['sent_notices'] == 0


def test_expired_subscription_does_not_keep_notice_pending(tmp_path, monkeypatch):
    store = register(tmp_path, 'gone', 'ok')
    transport = WebPushTransport(config(tmp_path))

    class Gone(Exception):
        response = type('Response', (), {'status_code': 410})()

    def send(sub, payload):
        if sub['endpoint'].endswith('/gone'):
            raise Gone()

    monkeypatch.setattr(transport, 'send', send)
    result = transport.deliver(KEYED)
    assert result == {'sent': 1, 'expired': 1, 'subscriptions': 2, 'complete': True}
    assert list(store.load()) == ['https://push.example/ok']


def test_key_rotation_at_same_endpoint_is_a_new_target(tmp_path, monkeypatch):
    store = register(tmp_path, 'a')
    transport = WebPushTransport(config(tmp_path))
    calls = []
    monkeypatch.setattr(transport, 'send', lambda sub, payload: calls.append(sub))
    assert transport.deliver(KEYED)['complete'] is True
    assert transport.deliver(KEYED)['sent'] == 0
    store.put(subscription('a', auth='rotated-auth'))
    assert transport.deliver(KEYED)['sent'] == 1
    assert len(calls) == 2


def test_ack_commit_survives_global_seen_commit_failure(tmp_path, monkeypatch):
    register(tmp_path, 'a')
    transport = WebPushTransport(config(tmp_path))
    calls = []
    monkeypatch.setattr(transport, 'send', lambda sub, payload: calls.append(sub))
    dispatch = PushDispatch(transport, tmp_path / 'seen.json')

    def fail_save(*args):
        raise OSError('disk full')

    monkeypatch.setattr(dispatch, '_save', fail_save)
    with pytest.raises(OSError):
        dispatch.dispatch(NOTICE)
    assert len(calls) == 1
    assert PushDispatch(transport, tmp_path / 'seen.json').dispatch(NOTICE)['sent_notices'] == 1
    assert len(calls) == 1


def test_corrupt_ack_state_does_not_replay_previously_delivered_targets(tmp_path, monkeypatch):
    register(tmp_path, 'a')
    transport = WebPushTransport(config(tmp_path))
    transport.ack_file.write_text('{bad')
    calls = []
    monkeypatch.setattr(transport, 'send', lambda sub, payload: calls.append(sub))
    with pytest.raises(SubscriptionStoreCorrupt):
        transport.deliver(KEYED)
    assert calls == []


def test_no_subscriptions_keeps_notice_eligible_for_later_delivery(tmp_path, monkeypatch):
    transport = WebPushTransport(config(tmp_path))
    seen = tmp_path / 'seen.json'
    assert PushDispatch(transport, seen).dispatch(NOTICE)['failed_notices'] == 1
    assert not seen.exists()
    register(tmp_path, 'a')
    monkeypatch.setattr(transport, 'send', lambda *_: None)
    assert PushDispatch(transport, seen).dispatch(NOTICE)['sent_notices'] == 1


def test_ack_state_is_private_bounded_and_contains_no_endpoint_or_payload(tmp_path, monkeypatch):
    register(tmp_path, 'a')
    transport = WebPushTransport(config(tmp_path), max_acknowledged_notices=2)
    monkeypatch.setattr(transport, 'send', lambda *_: None)
    for key in ('z-old', 'y-old', 'a-new'):
        transport.deliver({**KEYED, 'key': key})
    raw = transport.ack_file.read_text()
    assert list(json.loads(raw)['notices']) == ['y-old', 'a-new']
    assert all(value not in raw for value in ('https://', 'test-auth', 'test-key', KEYED['body']))
    assert transport.ack_file.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob('.push-acks-*'))


def test_rotated_subscription_is_not_removed_after_old_endpoint_expiry(tmp_path, monkeypatch):
    store = register(tmp_path, 'a')
    transport = WebPushTransport(config(tmp_path))

    class Gone(Exception):
        response = type('Response', (), {'status_code': 404})()

    def send(sub, payload):
        store.put(subscription('a', auth='replacement-auth'))
        raise Gone()

    monkeypatch.setattr(transport, 'send', send)
    assert transport.deliver(KEYED)['complete'] is False
    assert store.load()['https://push.example/a']['keys']['auth'] == 'replacement-auth'


def test_all_expired_targets_do_not_settle_before_any_valid_recipient(tmp_path, monkeypatch):
    register(tmp_path, 'gone')
    transport = WebPushTransport(config(tmp_path))
    seen = tmp_path / 'seen.json'

    class Gone(Exception):
        response = type('Response', (), {'status_code': 410})()

    monkeypatch.setattr(transport, 'send', lambda *_: (_ for _ in ()).throw(Gone()))
    assert PushDispatch(transport, seen).dispatch(NOTICE)['failed_notices'] == 1
    assert not seen.exists()
    register(tmp_path, 'replacement')
    monkeypatch.setattr(transport, 'send', lambda *_: None)
    assert PushDispatch(transport, seen).dispatch(NOTICE)['sent_notices'] == 1
