from dataclasses import dataclass

@dataclass(frozen=True)
class LocalComputeCandidate:
    binding: str
    provider: str = 'LOCAL'
    tier: str = 'LOCAL'
    health: str = 'UNAVAILABLE'
    active: bool = False
    reason: str | None = None
    capabilities: tuple[str,...] = ('CHAT',)
    model: str = ''
    roles: tuple[str,...] = ()
    slot: str = ''
    characteristics: tuple[str,...] = ()
    # Only an actually same-host model may receive private LOCAL_ONLY content.
    # A Windows/MainPC OpenAI endpoint is remote even on a private 1GbE cable.
    same_host: bool = True

class LocalComputeRegistry:
    """Presentation/routing-facing inventory only. The actual local runtime stays behind an adapter."""
    def __init__(self, discovery=None): self.discovery=discovery
    def candidates(self):
        if self.discovery is None: return ()
        rows=self.discovery()
        out=[]
        for row in rows:
            if isinstance(row,LocalComputeCandidate): out.append(row); continue
            out.append(LocalComputeCandidate(**row))
        return tuple(out)

class CompositeLocalComputeRegistry:
    """Union of independently owned local-compute discovery sources."""
    def __init__(self,*registries):self.registries=tuple(registries)
    def candidates(self):
        out=[];seen=set()
        for registry in self.registries:
            for candidate in registry.candidates():
                if candidate.binding in seen:continue
                seen.add(candidate.binding);out.append(candidate)
        return tuple(out)
