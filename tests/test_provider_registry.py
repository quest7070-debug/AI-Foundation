import pytest
from ai_foundation.provider_registry import SQLiteProviderRegistry

def test_provider_cards_group_credentials_and_hide_keys(tmp_path):
    r=SQLiteProviderRegistry(tmp_path/'providers.sqlite')
    r.upsert('gemini-a','gemini',short_remaining=80,short_reset='22m',long_remaining=60,long_reset='11d')
    r.upsert('gemini-b','gemini',short_remaining=70,short_reset='20m',long_remaining=55,long_reset='11d',active=True)
    cards=r.cards()
    assert len(cards)==1 and cards[0].provider=='GEMINI' and cards[0].credentials==2
    assert cards[0].short_remaining==70
    assert 'gemini-a' not in repr(cards)

def test_free_registration_preserves_unknown_quota_without_fabrication(tmp_path):
    r=SQLiteProviderRegistry(tmp_path/'providers.sqlite')
    r.upsert('x','gemini')
    c=r.credential('x')
    assert c['tier']=='FREE' and c['short_remaining'] is None and c['long_remaining'] is None

def test_last_credential_delete_removes_card(tmp_path):
    r=SQLiteProviderRegistry(tmp_path/'providers.sqlite')
    r.upsert('x','groq',short_remaining=90,long_remaining=80)
    r.remove('x')
    assert r.cards()==()

def test_credentials_preserve_quota_reset_reason_and_observation_time(tmp_path):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite');r.upsert('x','groq',short_remaining=80,short_reset='7s',long_remaining=25,long_reset='1h',reason='observed')
 c=r.credentials()[0];assert c['short_reset']=='7s' and c['long_reset']=='1h' and c['reason']=='observed' and c['updated_at']>0

def test_card_exposes_latest_observation_time(tmp_path):
 import time
 r=SQLiteProviderRegistry(tmp_path/'p.db');r.upsert('a','GROQ','FREE','ONLINE',90,'1m',80,'1d');first=r.cards()[0].updated_at
 time.sleep(.001);r.observe('a',health='DOWN',reason='probe failed');c=r.cards()[0]
 assert c.updated_at>=first and c.health=='DOWN' and c.reason=='probe failed'

def test_card_reset_belongs_to_limiting_credential_not_independent_min(tmp_path):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite')
 r.upsert('a','groq',short_remaining=20,short_reset='9m',long_remaining=80,long_reset='1h')
 r.upsert('b','groq',short_remaining=80,short_reset='1m',long_remaining=10,long_reset='9h')
 c=r.cards()[0]
 assert (c.short_remaining,c.short_reset)==(20,'9m')
 assert (c.long_remaining,c.long_reset)==(10,'9h')

def test_custom_provider_transport_metadata_round_trips(tmp_path):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite')
 r.upsert('x','my-api',endpoint='https://example.invalid/v1/chat/completions',model='model-x',auth_style='bearer',protocol='openai-chat')
 c=r.credential('x'); assert (c['endpoint'],c['model'],c['auth_style'],c['protocol'])==('https://example.invalid/v1/chat/completions','model-x','bearer','openai-chat')
 assert r.credentials()[0]['endpoint']==c['endpoint']

def test_online_observation_clears_stale_failure_reason(tmp_path):
 r=SQLiteProviderRegistry(tmp_path/'p.sqlite')
 r.upsert('b','GROQ',health='DOWN',reason='HTTP 503')
 r.observe('b',health='ONLINE',reason=None)
 m=r.credential('b')
 assert m['health']=='ONLINE' and m['reason'] is None
