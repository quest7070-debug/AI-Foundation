"""Exact-match authority records for deterministic Kandev clarification answers.

This is deliberately not a natural-language resolver. A record is authoritative
only for one exact question generation digest and explicit option IDs.
"""
from dataclasses import dataclass
import json
import os
import subprocess
import tempfile
from pathlib import Path
from .question_bridge import question_identity

@dataclass(frozen=True)
class CanonQuestionDecision:
    task_id: str
    question_digest: str
    answers: tuple[dict, ...]
    authority_source: str
    authority_revision: str

class CanonQuestionAuthority:
    def __init__(self,path,repo_root=None):
        self.path=Path(path)
        self.repo_root=Path(repo_root).resolve() if repo_root else None

    def _rows(self):
        if not self.path.exists(): return ()
        raw=json.loads(self.path.read_text())
        if not isinstance(raw,dict) or raw.get('schema_version')!=1 or not isinstance(raw.get('decisions'),list):
            raise ValueError('invalid question authority store')
        return tuple(raw['decisions'])

    def resolve(self,bundle):
        ident=question_identity(bundle)
        matches=[r for r in self._rows() if r.get('task_id')==ident.task_id and r.get('question_digest')==ident.digest]
        if len(matches)!=1:return None
        r=matches[0]
        answers=r.get('answers')
        if not isinstance(answers,list) or not answers:return None
        by_q={str(q.get('question_id')):{str(o.get('option_id')) for o in q.get('options',())} for q in bundle.get('questions',())}
        if {str(a.get('question_id')) for a in answers}!=set(by_q):return None
        for a in answers:
            qid=str(a.get('question_id')); selected=a.get('selected_options',[])
            if not isinstance(selected,list) or not set(map(str,selected))<=by_q[qid]:return None
            if a.get('custom_text'):return None
        if not r.get('authority_source') or not r.get('authority_revision'):return None
        if not self._authority_current(r):return None
        return answers

    def _authority_current(self,row):
        if self.repo_root is None:return True
        source=str(row.get('authority_source',''))
        if not source.startswith('docs/'):return False
        target=(self.repo_root/source).resolve()
        if self.repo_root not in target.parents or not target.is_file():return False
        try:
            current=subprocess.check_output(['git','hash-object',str(target)],cwd=self.repo_root,text=True,timeout=3).strip()
        except Exception:return False
        return current==str(row.get('authority_revision',''))

    def promote(self,bundle,answers,*,authority_source,authority_revision):
        ident=question_identity(bundle)
        candidate={'schema_version':1,'decisions':[{'task_id':ident.task_id,'question_digest':ident.digest,'answers':answers,'authority_source':authority_source,'authority_revision':authority_revision}]}
        probe=self.path.with_name(self.path.name+'.probe')
        probe.write_text(json.dumps(candidate))
        try:
            check=CanonQuestionAuthority(probe,self.repo_root)
            if check.resolve(bundle)!=answers:raise ValueError('authority promotion rejected')
        finally:
            probe.unlink(missing_ok=True)
        rows=list(self._rows())
        if any(r.get('task_id')==ident.task_id and r.get('question_digest')==ident.digest for r in rows):
            raise ValueError('authority decision already exists')
        payload={'schema_version':1,'decisions':rows+candidate['decisions']}
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix=self.path.name+'.',dir=self.path.parent)
        try:
            with os.fdopen(fd,'w') as f:
                json.dump(payload,f,ensure_ascii=False,separators=(',',':'));f.flush();os.fsync(f.fileno())
            os.replace(tmp,self.path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
        return ident.digest
