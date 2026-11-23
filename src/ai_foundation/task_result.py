import json
from dataclasses import asdict, dataclass

@dataclass(frozen=True)
class TaskResult:
    output: str
    verification: str = 'VERIFIED'
    route_kind: str | None = None
    evidence: tuple[str, ...] = ()
    route_binding: str | None = None

    def encode(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, separators=(',', ':'))

    @classmethod
    def decode(cls, value):
        # Only a non-string input is inert. Malformed *string* receipts must
        # keep their existing literal passthrough contract for old callers.
        if type(value) is not str:
            return cls('')
        try:
            data = json.loads(value)
            if type(data) is not dict or type(data.get('output')) is not str:
                return cls(value or '')
            verification = data.get('verification', 'VERIFIED')
            if type(verification) is not str:
                return cls(value or '')
            route_kind = data.get('route_kind')
            route_binding = data.get('route_binding')
            if any(v is not None and type(v) is not str for v in (route_kind, route_binding)):
                return cls(value or '')
            evidence = data.get('evidence', [])
            if evidence is None:
                evidence = []
            if type(evidence) is not list or any(type(v) is not str for v in evidence):
                return cls(value or '')
            return cls(data['output'], verification, route_kind, tuple(evidence), route_binding)
        except (TypeError, ValueError, KeyError):
            return cls(value or '')
