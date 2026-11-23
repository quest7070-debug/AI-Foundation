from dataclasses import dataclass
import math

@dataclass(frozen=True)
class QuotaWindow:
    remaining:float; reset:str|None; source:str

def _pct(remaining,limit):
    try:
        r=float(remaining); l=float(limit)
        if not math.isfinite(r) or not math.isfinite(l) or l<=0:
            return None
        return max(0.0,min(100.0,100.0*r/l))
    except (TypeError,ValueError): return None

def groq_quota(headers):
    h={str(k).lower():v for k,v in headers.items()}
    short=_pct(h.get('x-ratelimit-remaining-tokens'),h.get('x-ratelimit-limit-tokens'))
    long=_pct(h.get('x-ratelimit-remaining-requests'),h.get('x-ratelimit-limit-requests'))
    if short is None or long is None: return None
    return (
      QuotaWindow(short,h.get('x-ratelimit-reset-tokens'),'groq-response-headers'),
      QuotaWindow(long,h.get('x-ratelimit-reset-requests'),'groq-response-headers'),
    )

def mistral_short_quota(headers):
    h={str(k).lower():v for k,v in headers.items()}
    remaining=h.get('x-ratelimit-remaining'); limit=h.get('x-ratelimit-limit')
    value=_pct(remaining,limit)
    return QuotaWindow(value,h.get('x-ratelimit-reset'),'mistral-response-headers') if value is not None else None