"""Canonical execution topology for Foundation capabilities.

This is the single authority for whether a capability consumes an LLM route.
Provider/model capability metadata is capacity evidence; it does not make an
unused LLM route part of a host-owned execution path.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class CapabilityTopology:
    function:str
    uses_llm_route:bool

_TOPOLOGY={
    'CHAT':CapabilityTopology('CHAT',True),
    'SEARCH':CapabilityTopology('SEARCH',True),
    'CODE':CapabilityTopology('CODE',False),
    'DATA':CapabilityTopology('DATA',False),
    'FILES':CapabilityTopology('FILES',False),
    'PC_CONTROL':CapabilityTopology('PC_CONTROL',False),
    'VISION':CapabilityTopology('VISION',True),
}

def topology(function:str)->CapabilityTopology:
    from .routing_capabilities import normalize_capability
    key=normalize_capability(function)
    try:return _TOPOLOGY[key]
    except KeyError as e:raise ValueError('unknown capability') from e

def uses_llm_route(function:str)->bool:return topology(function).uses_llm_route
