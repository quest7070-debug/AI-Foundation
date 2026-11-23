from dataclasses import dataclass
@dataclass(frozen=True)
class QuotaEvidence:
 provider:str; short_remaining:float|None; short_reset:str|None; long_remaining:float|None; long_reset:str|None; authoritative:bool; source:str; scope:str

def groq_header_evidence(headers):
 h={str(k).lower():str(v) for k,v in headers.items()}
 def pct(rem,lim):
  try:
   r=float(h[rem]); l=float(h[lim]); return max(0.0,min(100.0,r/l*100)) if l>0 else None
  except (KeyError,ValueError,ZeroDivisionError):return None
 short=pct('x-ratelimit-remaining-tokens','x-ratelimit-limit-tokens')
 long=pct('x-ratelimit-remaining-requests','x-ratelimit-limit-requests')
 return QuotaEvidence('GROQ',short,h.get('x-ratelimit-reset-tokens'),long,h.get('x-ratelimit-reset-requests'),short is not None and long is not None,'groq-response-headers','organization/project effective limits')

def mistral_header_evidence(headers):
 h={str(k).lower():str(v) for k,v in headers.items()}
 try: rem=float(h['x-ratelimit-remaining']); lim=float(h['x-ratelimit-limit']); short=max(0,min(100,rem/lim*100)) if lim>0 else None
 except (KeyError,ValueError,ZeroDivisionError): short=None
 return QuotaEvidence('MISTRAL',short,h.get('x-ratelimit-reset'),None,None,False,'mistral-response-headers','workspace/organization; long free allowance not machine-readable from normal key')

def free_registration_allowed(e): return bool(e.authoritative and e.short_remaining is not None and e.long_remaining is not None)
