import json,os,tempfile
from pathlib import Path
THEMES=('I','C')
class PresentationPreferences:
 def __init__(self,path,storage_admission=None):self.path=Path(path);self.storage_admission=storage_admission
 def get(self):
  try:
   x=json.loads(self.path.read_text()).get('theme','I');return x if x in THEMES else 'I'
  except (OSError,ValueError,TypeError):return 'I'
 def set(self,theme):
  if self.storage_admission:self.storage_admission.require('presentation preference')
  if theme not in THEMES:raise ValueError('unknown theme')
  self.path.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(dir=self.path.parent,prefix='.presentation-',text=True)
  try:
   with os.fdopen(fd,'w') as f:json.dump({'theme':theme},f);f.flush();os.fsync(f.fileno())
   os.replace(tmp,self.path)
  finally:
   try:os.unlink(tmp)
   except FileNotFoundError:pass
