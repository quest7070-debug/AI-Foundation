from dataclasses import dataclass

@dataclass(frozen=True)
class QualityContract:
    name: str
    required_fields: tuple[str, ...]
    checks: tuple = ()

    def evaluate(self,result):
        # A property getter may raise; absence is a failed requirement, not a crash.
        missing=[]
        for name in self.required_fields:
            try:
                if getattr(result,name) is None:
                    missing.append(name)
            except Exception:
                missing.append(name)
        missing=tuple(missing)
        failed=[]
        for name,check in self.checks:
            try: ok=check(result) is True
            except Exception: ok=False
            if not ok: failed.append(name)
        return QualityResult(self.name,not missing and not failed,missing,tuple(failed))

@dataclass(frozen=True)
class QualityResult:
    contract: str
    passed: bool
    missing_fields: tuple[str, ...]
    failed_checks: tuple[str, ...]
