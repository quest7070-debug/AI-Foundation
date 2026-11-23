import json
from urllib import request,error
from .provider_onboarding import ProbeResult
from .quota_evidence import groq_header_evidence,mistral_header_evidence,free_registration_allowed
from .provider_catalog import spec

class LiveProviderProbe:
    """Validate a credential against its actual provider. Never invent quota evidence."""
    def __init__(self,transport,opener=None,timeout=30):
        self.transport=transport
        self.opener=opener or request.build_opener().open
        self.timeout=timeout

    def _gemini(self,secret):
        # Gemini is not OpenAI-compatible: authenticate with x-goog-api-key.
        req=request.Request(
            'https://generativelanguage.googleapis.com/v1beta/models',
            method='GET',
            headers={'x-goog-api-key':secret,'Accept':'application/json','User-Agent':'AI-Foundation/1.0'},
        )
        try:
            with self.opener(req,timeout=self.timeout) as resp:
                resp.read(1)
                return ProbeResult('GEMINI','ONLINE')
        except error.HTTPError as exc:
            if exc.code in (400,401,403): return ProbeResult('GEMINI','CREDENTIAL_ERROR',reason=f'HTTP {exc.code}')
            if exc.code==429:return ProbeResult('GEMINI','RATE_LIMITED',reason='HTTP 429')
            return ProbeResult('GEMINI','DOWN',reason=f'HTTP {exc.code}')
        except Exception:
            return ProbeResult('GEMINI','DOWN',reason='provider validation transport failed')

    def _github(self,secret):
        req=request.Request('https://api.github.com/user',method='GET',headers={'Authorization':f'Bearer {secret}','Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'AI-Foundation/1.0'})
        try:
            with self.opener(req,timeout=self.timeout) as resp:
                resp.read(1)
                return ProbeResult('GITHUB','ONLINE',reason='LLM capability not verified')
        except error.HTTPError as exc:
            if exc.code in (401,403): return ProbeResult('GITHUB','CREDENTIAL_ERROR',reason=f'HTTP {exc.code}')
            if exc.code==429:return ProbeResult('GITHUB','RATE_LIMITED',reason='HTTP 429')
            return ProbeResult('GITHUB','DOWN',reason=f'HTTP {exc.code}')
        except Exception:
            return ProbeResult('GITHUB','DOWN',reason='provider validation transport failed')

    def _bearer_models(self,provider,secret,provider_spec):
        req=request.Request(provider_spec.models_endpoint,method='GET',headers={'Authorization':f'Bearer {secret}','Accept':'application/json','User-Agent':'AI-Foundation/1.0'})
        try:
            with self.opener(req,timeout=self.timeout) as resp:
                resp.read(1)
                return ProbeResult(provider,'ONLINE',reason='quota evidence unavailable')
        except error.HTTPError as exc:
            if exc.code in (401,403): return ProbeResult(provider,'CREDENTIAL_ERROR',reason=f'HTTP {exc.code}')
            if exc.code==429:return ProbeResult(provider,'RATE_LIMITED',reason='HTTP 429')
            return ProbeResult(provider,'DOWN',reason=f'HTTP {exc.code}')
        except Exception:
            return ProbeResult(provider,'DOWN',reason='provider validation transport failed')

    def _openai_compatible(self,provider,secret):
        # Validation uses a minimal real inference so the same auth/endpoint path as runtime is proved.
        provider_spec=spec(provider)
        if not provider_spec or not provider_spec.model:return ProbeResult(provider,'UNVERIFIED',reason='provider selection required')
        payload={'model':provider_spec.model,'messages':[{'role':'user','content':'Reply with OK.'}],'max_tokens':1,'temperature':0}
        if provider_spec.quota_style=='groq':
            payload['max_completion_tokens']=payload.pop('max_tokens')
        try: response=self.transport.send(provider,secret,payload)
        except Exception:return ProbeResult(provider,'DOWN',reason='provider validation transport failed')
        if response.status in (401,403):return ProbeResult(provider,'CREDENTIAL_ERROR',reason=f'HTTP {response.status}')
        if response.status==429:return ProbeResult(provider,'RATE_LIMITED',reason='HTTP 429')
        if response.status>=400:
            # Preserve only bounded provider status/code; never include response body or secret.
            return ProbeResult(provider,'DOWN',reason=f'HTTP {response.status}')
        if provider_spec.quota_style=='groq':
            e=groq_header_evidence(response.headers)
            return ProbeResult(provider,'ONLINE',e.short_remaining,e.short_reset,e.long_remaining,e.long_reset,
                               None if free_registration_allowed(e) else 'quota evidence unavailable')
        if provider_spec.quota_style=='mistral':
            e=mistral_header_evidence(response.headers)
            return ProbeResult(provider,'ONLINE',e.short_remaining,e.short_reset,e.long_remaining,e.long_reset,
                               'long quota evidence unavailable' if e.long_remaining is None else None)
        return ProbeResult(provider,'ONLINE',reason='quota evidence unavailable')

    def _native_search(self,provider,secret):
        provider_spec=spec(provider)
        payload={'query':'OpenAI'}
        if provider=='TAVILY':payload['max_results']=1
        elif provider=='EXA':payload.update({'numResults':1,'contents':{'text':True}})
        headers={'Content-Type':'application/json','Accept':'application/json','User-Agent':'AI-Foundation/1.0'}
        headers['x-api-key' if provider_spec.auth_style=='x-api-key' else 'Authorization']=secret if provider_spec.auth_style=='x-api-key' else f'Bearer {secret}'
        req=request.Request(provider_spec.endpoint,data=json.dumps(payload).encode(),method='POST',headers=headers)
        try:
            with self.opener(req,timeout=self.timeout) as resp:
                raw=resp.read(65537)
                if len(raw)>65536:return ProbeResult(provider,'DOWN',reason='provider response too large')
                data=json.loads(raw or b'{}')
                if not isinstance(data.get('results'),list):return ProbeResult(provider,'DOWN',reason='search response invalid')
                return ProbeResult(provider,'ONLINE',reason='quota evidence unavailable')
        except error.HTTPError as exc:
            if exc.code in (401,403):return ProbeResult(provider,'CREDENTIAL_ERROR',reason=f'HTTP {exc.code}')
            if exc.code==429:return ProbeResult(provider,'RATE_LIMITED',reason='HTTP 429')
            return ProbeResult(provider,'DOWN',reason=f'HTTP {exc.code}')
        except Exception:return ProbeResult(provider,'DOWN',reason='provider validation transport failed')

    def _tavily(self,secret):
        # Minimal native search proves both credential and actual SEARCH capability.
        req=request.Request('https://api.tavily.com/search',data=json.dumps({'query':'OpenAI','max_results':1}).encode(),method='POST',headers={'Authorization':f'Bearer {secret}','Content-Type':'application/json','Accept':'application/json','User-Agent':'AI-Foundation/1.0'})
        try:
            with self.opener(req,timeout=self.timeout) as resp:
                raw=resp.read(65537)
                if len(raw)>65536:return ProbeResult('TAVILY','DOWN',reason='provider response too large')
                data=json.loads(raw or b'{}')
                if not isinstance(data.get('results'),list):return ProbeResult('TAVILY','DOWN',reason='search response invalid')
                return ProbeResult('TAVILY','ONLINE',reason='quota evidence unavailable')
        except error.HTTPError as exc:
            if exc.code in (401,403):return ProbeResult('TAVILY','CREDENTIAL_ERROR',reason=f'HTTP {exc.code}')
            if exc.code==429:return ProbeResult('TAVILY','RATE_LIMITED',reason='HTTP 429')
            return ProbeResult('TAVILY','DOWN',reason=f'HTTP {exc.code}')
        except Exception:return ProbeResult('TAVILY','DOWN',reason='provider validation transport failed')

    def probe(self,secret,provider_hint=None):
        provider=(provider_hint or '').upper()
        provider_spec=spec(provider)
        if provider_spec and provider_spec.auth_style=='gemini':return self._gemini(secret)
        if provider_spec and provider_spec.auth_style=='github':return self._github(secret)
        if provider_spec and provider_spec.probe_style=='search':return self._native_search(provider,secret)
        if provider_spec and provider_spec.auth_style=='bearer':
            if provider_spec.probe_style=='models' and provider_spec.models_endpoint:return self._bearer_models(provider,secret,provider_spec)
            return self._openai_compatible(provider,secret)
        return ProbeResult(provider or None,'UNVERIFIED',reason='provider selection required')
