import subprocess
from pathlib import Path
from .core import Decision, TaskPlan

class CedarPolicyBoundary:
    def __init__(self, cedar: str | Path, policies: str | Path, schema: str | Path, entities: str | Path, principal: str = 'User::"local-owner"'):
        self.cedar, self.policies, self.schema, self.entities = map(str,(cedar,policies,schema,entities))
        self.principal = principal
        self.revision = self._revision()

    def _revision(self):
        import hashlib
        h=hashlib.sha256()
        for path in (self.policies,self.schema,self.entities):
            try: h.update(Path(path).read_bytes())
            except OSError: return ''
        return h.hexdigest()

    def authorize(self, plan: TaskPlan) -> Decision:
        current_revision=self._revision()
        if not current_revision or current_revision != self.revision:
            return Decision.DENY
        if plan.policy_revision and plan.policy_revision != current_revision:
            return Decision.DENY
        if any(c in plan.target for c in ('"', "\n", "\r", "\x00")):
            return Decision.DENY
        action = plan.action if plan.action in {'read','write','delete','send_email','production_deploy','purchase'} else plan.action
        cmd=[self.cedar,'authorize','-l',self.principal,'-a',f'Action::"{action}"','-r',f'Target::"{plan.target}"',
             '-p',self.policies,'-s',self.schema,'--schema-format','cedar','--entities',self.entities]
        try:
            result=subprocess.run(cmd,capture_output=True,text=True,timeout=5)
        except (OSError, subprocess.SubprocessError):
            return Decision.DENY
        if result.returncode != 0:
            return Decision.DENY
        out=(result.stdout+'\n'+result.stderr).lower()
        return Decision.ALLOW if 'allow' in out else Decision.DENY
