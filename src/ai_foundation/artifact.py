from dataclasses import dataclass
from typing import Protocol
from hashlib import sha256
from pathlib import Path

TEXT_ARTIFACT_MAX_BYTES = 1024 * 1024
TEXT_ARTIFACT_SUFFIXES = frozenset({'.txt', '.md', '.csv', '.tsv', '.json'})


@dataclass(frozen=True)
class TextArtifactResult:
    target: str
    status: str
    utf8_sha256: str | None = None
    utf8_bytes: int | None = None

    @property
    def verified(self):
        return self.status == 'VERIFIED_COMPLETE' and self.utf8_sha256 is not None


def produce_text_artifact(execution, run_id: str, target: str, content: str) -> TextArtifactResult:
    """Use an existing write-scoped FILES execution; never create a new grant.

    Hashes describe the independently observed UTF-8 text, not binary-format
    validity, file delivery or a download URL. One target per host run has one
    durable effect identity, so an ambiguous repeat reconciles without a write.
    """
    if not isinstance(run_id, str) or not run_id:
        raise ValueError('host run identity required')
    if not isinstance(target, str) or not target or not isinstance(content, str):
        raise ValueError('artifact target and text required')
    if Path(target).suffix.lower() not in TEXT_ARTIFACT_SUFFIXES:
        raise ValueError('unsupported text artifact format')
    encoded = content.encode('utf-8')
    if len(encoded) > TEXT_ARTIFACT_MAX_BYTES:
        raise ValueError('text artifact exceeds size limit')
    if not execution.scope.write:
        raise PermissionError('file write capability disabled')
    tools = execution.for_run(run_id)
    safe = tools.write_capability.authorize_target(target)
    execution.protected.validate_write(safe)
    relative = Path(safe).relative_to(Path(execution.scope.normalized_root())).as_posix()
    identity = run_id + ':text-artifact:' + sha256(safe.encode('utf-8')).hexdigest()
    # Keep identity observation, reconciliation-recipe registration, Guard and
    # final readback in one host-local transaction. Otherwise two writers can
    # both observe no effect and the loser can replace the winner's recipe.
    parent = Path(safe).parent
    if not parent.is_dir():
        raise FileNotFoundError('artifact output root must be provisioned by the host')
    from .filesystem_lock import exclusive_file_lock
    # A target-local inode also covers overlapping host scopes for the same
    # normalized target, while independent output files remain concurrent.
    lock = parent / ('.foundation-text-artifact-' + sha256(safe.encode('utf-8')).hexdigest() + '.lock')
    with exclusive_file_lock(lock):
        return _produce_text_artifact_locked(execution, run_id, safe, relative, identity, content, encoded)


def _produce_text_artifact_locked(execution, run_id, safe, relative, identity, content, encoded):
    guard = execution.for_run(run_id).gateway.guard
    previous = guard.get_effect(identity)
    if previous is not None and (previous.run_id, previous.target, previous.expected) != (run_id, safe, content):
        # Check before registering any reconciliation recipe; a later model
        # revision must not replace the original effect's expected content.
        return TextArtifactResult(relative, 'ARTIFACT_IDENTITY_CONFLICT')
    status = execution.write(run_id, safe, content, effect_id=identity)
    if status != 'VERIFIED_COMPLETE':
        return TextArtifactResult(relative, status)
    try:
        observed = execution.read(run_id, safe)
    except Exception:
        return TextArtifactResult(relative, 'ARTIFACT_READBACK_UNAVAILABLE')
    if observed != content:
        return TextArtifactResult(relative, 'FAILED_ARTIFACT_READBACK')
    return TextArtifactResult(relative, status, sha256(observed.encode('utf-8')).hexdigest(), len(encoded))


class ArtifactPort(Protocol):
 def create(self,target:str,content:str)->str: ...
 def validate(self,target:str)->str: ...
@dataclass(frozen=True)
class ArtifactResult:
 target:str; create_result:str; validation:str
 @property
 def verified(self): return self.validation=='VERIFIED'
@dataclass
class ArtifactSpecialist:
 port:ArtifactPort
 def produce(self,target:str,content:str)->ArtifactResult:
  created=self.port.create(target,content)
  checked=self.port.validate(target)
  return ArtifactResult(target,created,checked)
