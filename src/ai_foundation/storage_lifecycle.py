"""Storage lifecycle policy and read-only host inventory.

This module classifies ownership and lifecycle. It never deletes external or
unknown state; mutation remains in owner-specific services (retention, backup,
attachment cleanup, etc.).
"""
from dataclasses import dataclass
from pathlib import Path
import shutil

@dataclass(frozen=True)
class LifecycleRule:
    owner:str; growth:str; disposition:str; max_bytes:int|None=None; max_generations:int|None=None

RULES={
 'foundation-trace':LifecycleRule('foundation','bounded-generations','owner-cleanup',8*1024**2*4,4),
 'foundation-backup':LifecycleRule('foundation','generational','owner-retention',None,3),
 'llama-log':LifecycleRule('llama-swap','append','external-owner',256*1024**2,None),
 'toolhive-log':LifecycleRule('toolhive','append','external-owner',256*1024**2,None),
 'docker':LifecycleRule('docker','host-cache-and-volumes','external-owner'),
 'model-cache':LifecycleRule('huggingface/llama-swap','cache-and-configured-artifacts','external-owner'),
 'search-index':LifecycleRule('librechat/meili/postgres','derived-and-authoritative-mixed','external-owner'),
}

def tree_bytes(path):
 p=Path(path)
 if not p.exists():return 0
 if p.is_file():return p.stat().st_size
 total=0
 for x in p.rglob('*'):
  try:
   if x.is_file() and not x.is_symlink():total+=x.stat().st_size
  except OSError:continue
 return total

def inventory(data_dir,home=None):
 root=Path(data_dir);home=Path(home or Path.home())
 rows={
  'foundation-data':tree_bytes(root),
  'foundation-backup':tree_bytes(root.parent/'AI-Foundation-backup'),
  'llama-log':tree_bytes(root/'local-compute'/'llama-swap.log'),
  'model-cache':tree_bytes(home/'.cache'/'huggingface'),
  'toolhive-state':tree_bytes(home/'Library'/'Application Support'/'toolhive'),
 }
 return rows

def backup_generation_plan(paths,keep=3):
 """Compatibility entry point for verified-generation retention; never deletes."""
 return backup_retention_plan(paths,keep)

def validate_backup_generation(path):
 """Return True only for a complete, self-consistent Foundation backup generation."""
 from .productization import verify_backup
 try: verify_backup(path)
 except (OSError,ValueError): return False
 return True

def _validate_backup_keep(keep):
 if type(keep) is not int or keep < 1:
  raise ValueError('at least one backup generation must be retained')

def backup_retention_plan(paths,keep=3):
 """Pure plan: retain newest valid generations and never nominate the last valid one."""
 _validate_backup_keep(keep)
 valid=[Path(p) for p in paths if validate_backup_generation(p)]
 valid.sort(key=lambda p:p.stat().st_mtime,reverse=True)
 if len(valid)<=1:return ()
 return tuple(valid[keep:]) if len(valid)>keep else ()

def stale_artifact_plan(paths,live_path):
 """Pure plan for stale staging/quarantine candidates; live tree is structurally excluded."""
 live=Path(live_path).resolve();out=[]
 for raw in paths:
  p=Path(raw)
  try:r=p.resolve()
  except OSError:continue
  if r==live or live in r.parents or r in live.parents:continue
  if p.name.startswith('.') and ('.staging-' in p.name or p.name.endswith('.failed-update')):out.append(p)
 return tuple(out)


def backup_series_plan(parent,prefix,keep=3,protected=()):
 """Pure generation plan. Protected/LKG paths are never nominated."""
 _validate_backup_keep(keep)
 parent=Path(parent);protected={Path(x).resolve() for x in protected}
 candidates=[]
 if parent.exists():
  for p in parent.iterdir():
   if p.is_dir() and p.name.startswith(prefix) and validate_backup_generation(p):candidates.append(p)
 candidates.sort(key=lambda p:p.stat().st_mtime_ns,reverse=True)
 retained=set(candidates[:keep])|{p for p in candidates if p.resolve() in protected}
 return tuple(p for p in candidates if p not in retained and p.resolve() not in protected)

def apply_owned_directory_plan(paths,owner_parent):
 """Execute a precomputed owner-scoped plan; refuses paths outside owner parent."""
 import shutil
 owner=Path(owner_parent).resolve();removed=[]
 for raw in paths:
  p=Path(raw)
  if p.is_symlink() or not p.is_dir():raise ValueError('cleanup target must be a real directory')
  r=p.resolve()
  if r.parent!=owner:raise ValueError('cleanup path outside owner boundary')
  shutil.rmtree(p);removed.append(str(p))
 return tuple(removed)


class BackupMaintenance:
 """Explicit maintenance boundary; never runs at startup or from observation."""
 def __init__(self,parent,prefix='foundation-backup-',keep=3):
  _validate_backup_keep(keep)
  self.parent=Path(parent);self.prefix=prefix;self.keep=keep
 def plan(self,protected=()):return backup_series_plan(self.parent,self.prefix,self.keep,protected)
 def run(self,protected=()):return apply_owned_directory_plan(self.plan(protected),self.parent)

def classify_docker_inventory(images=(),containers=(),volumes=(),build_cache=()):
 """Read-only classification. Never treats a volume as reclaimable from age/name alone."""
 used_images={c.get('image_id') for c in containers if c.get('running')}
 rows=[]
 for x in images:
  state='live' if x.get('id') in used_images else ('dangling' if not x.get('tags') else 'unused')
  rows.append(('image',x.get('id'),state,int(x.get('size',0))))
 for x in volumes:rows.append(('volume',x.get('name'),'protected-persistent',int(x.get('size',0))))
 for x in build_cache:rows.append(('build-cache',x.get('id'),'cache',int(x.get('size',0))))
 return tuple(rows)

def configured_model_artifacts(config_text):
 """Extract absolute --model artifacts from host-owned llama-swap config."""
 import re
 return frozenset(Path(x).expanduser().resolve() for x in re.findall(r'--model\s+["\']([^"\']+)["\']',config_text))

def classify_model_files(files,configured=()):
 configured={Path(x).resolve() for x in configured};out=[]
 for raw in files:
  p=Path(raw);r=p.resolve();name=p.name
  if r in configured:state='configured-live'
  elif name.endswith(('.incomplete','.part','.tmp')):state='partial-download'
  else:state='cache-unreferenced'
  out.append((p,state))
 return tuple(out)


def model_cleanup_plan(files,configured=()):
 """Pure model-owner plan: only partial/unreferenced regular files, never configured artifacts."""
 return tuple(p for p,state in classify_model_files(files,configured) if state in {'partial-download','cache-unreferenced'} and p.is_file() and not p.is_symlink())

def apply_owned_file_plan(paths,owner_root):
 owner=Path(owner_root).resolve();removed=[]
 for raw in paths:
  p=Path(raw)
  if p.is_symlink() or not p.is_file():raise ValueError('cleanup target must be a real file')
  r=p.resolve()
  if owner!=r.parent and owner not in r.parents:raise ValueError('cleanup path outside owner boundary')
  p.unlink();removed.append(str(p))
 return tuple(removed)

def docker_cleanup_plan(rows):
 """Pure Docker-owner plan; volumes and live images are structurally ineligible."""
 return tuple((kind,ident) for kind,ident,state,_size in rows if (kind=='image' and state in {'unused','dangling'}) or (kind=='build-cache' and state=='cache'))

def file_tree_status(path, warn_files=100000, warn_largest_dir=10000):
 """Streaming inode/fan-out observation; memory is O(directory depth), not O(file count)."""
 import os
 root=Path(path); files=0;dirs=0;largest=0
 if not root.exists(): return {'files':0,'dirs':0,'largest_dir_files':0,'ok':True}
 stack=[root]
 while stack:
  cur=stack.pop();dirs+=1;direct=0
  try:
   with os.scandir(cur) as it:
    for e in it:
     try:
      if e.is_symlink():continue
      if e.is_dir(follow_symlinks=False):stack.append(Path(e.path))
      elif e.is_file(follow_symlinks=False):files+=1;direct+=1
     except OSError:continue
  except OSError:continue
  largest=max(largest,direct)
 return {'files':files,'dirs':dirs,'largest_dir_files':largest,'ok':files<warn_files and largest<warn_largest_dir}

def index_source_ratio(source_objects,index_objects,max_ratio=4.0):
 """Cheap divergence signal; zero source tolerates only zero index objects."""
 source=max(0,int(source_objects));index=max(0,int(index_objects))
 ratio=(index/source) if source else (0.0 if index==0 else float('inf'))
 return {'source_objects':source,'index_objects':index,'ratio':ratio,'ok':ratio<=max_ratio}
