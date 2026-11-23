"""Authenticated remote presentation boundary. It never owns Foundation decisions."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib,hmac,ipaddress,re,secrets,time
from urllib.parse import urlparse

_HOST=re.compile(r'^[A-Za-z0-9.-]+$')

@dataclass(frozen=True)
class RemoteAccessConfig:
    session_secret:str
    allowed_hosts:frozenset[str]
    cookie_secure:bool=True
    session_seconds:int=30*24*3600

    def __post_init__(self):
        if len(self.session_secret)<32: raise ValueError('remote access secret too short')
        if not self.allowed_hosts: raise ValueError('allowed hosts required')
        if self.session_seconds<60: raise ValueError('session lifetime too short')

class RemoteAccess:
    def __init__(self,config:RemoteAccessConfig): self.config=config
    def host_allowed(self,host_header:str)->bool:
        host=_host(host_header)
        if not host:return False
        if host in self.config.allowed_hosts:return True
        try:return ipaddress.ip_address(host).is_loopback
        except ValueError:return host in {'localhost'}
    def origin_allowed(self,origin:str|None,host_header:str,sec_fetch_site:str|None=None)->bool:
        # same-site is not same-origin; reject it for state-changing requests.
        if (sec_fetch_site or '').lower()=='cross-site':return False
        if not origin:return True
        try:p=urlparse(origin)
        except ValueError:return False
        if p.scheme not in {'http','https'}:return False
        # A Secure session must never authorize a downgrade-origin mutation.
        if self.config.cookie_secure and p.scheme!='https':return False
        return p.netloc.lower()==host_header.lower()
    def issue_session(self,now:int|None=None)->str:
        ts=int(time.time() if now is None else now); nonce=secrets.token_urlsafe(18); body=f'{ts}.{nonce}'
        sig=hmac.new(self.config.session_secret.encode(),body.encode(),hashlib.sha256).hexdigest()
        return f'{body}.{sig}'
    def session_valid(self,value:str,now:int|None=None)->bool:
        try:
            ts_s,nonce,sig=value.split('.',2); ts=int(ts_s)
            if not nonce:return False
        except (ValueError,AttributeError):return False
        current=int(time.time() if now is None else now)
        if ts>current+60 or current-ts>self.config.session_seconds:return False
        body=f'{ts}.{nonce}'; expected=hmac.new(self.config.session_secret.encode(),body.encode(),hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig,expected)

def _host(raw:str)->str:
    raw=(raw or '').strip()
    if not raw:return ''
    if raw.startswith('['):
        end=raw.find(']'); host=raw[1:end] if end>0 else ''
    elif raw.count(':')==1:host=raw.rsplit(':',1)[0]
    else:host=raw
    host=host.rstrip('.').lower()
    if not host:return ''
    try:ipaddress.ip_address(host);return host
    except ValueError:return host if _HOST.fullmatch(host) else ''
