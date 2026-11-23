"""Unified routing capability namespace.

A route is the user-visible capability, regardless of whether it is satisfied by a
native LLM/provider ability or by a composed program/tool path. If both satisfy the
same capability they share one route; distinct capabilities remain distinct routes.
"""
ROUTE_CAPABILITIES=('CHAT','SEARCH','CODE','DATA','FILES','PC_CONTROL','VISION')

def normalize_capability(name):
    aliases={
        'GENERAL':'CHAT','TEXT':'CHAT',
        'RESEARCH':'SEARCH',
        'CODING':'CODE',
        'STRUCTURED_DATA':'DATA',
        'ARTIFACT':'FILES',
        'COMPUTER_ACTION':'PC_CONTROL',
        'IMAGE':'VISION','IMAGE_ANALYSIS':'VISION','MULTIMODAL':'VISION',
    }
    value=(name or '').upper()
    return aliases.get(value,value)

def normalized_capabilities(candidate):
    return tuple(dict.fromkeys(normalize_capability(x) for x in (candidate.get('capabilities') or ())))

def supports(candidate,route):
    route=normalize_capability(route)
    if route not in ROUTE_CAPABILITIES:return False
    if route not in normalized_capabilities(candidate):return False
    if candidate.get('kind')=='LOCAL':return True
    return bool(candidate.get('protocol') and candidate.get('model'))
