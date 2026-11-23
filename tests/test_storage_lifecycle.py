from pathlib import Path
from ai_foundation.storage_lifecycle import inventory,backup_generation_plan,RULES

def test_inventory_is_read_only_and_owner_scoped(tmp_path):
 root=tmp_path/'data';root.mkdir();(root/'x').write_bytes(b'123');home=tmp_path/'home';(home/'.cache/huggingface').mkdir(parents=True);(home/'.cache/huggingface/m').write_bytes(b'12345')
 before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()};rows=inventory(root,home)
 assert rows['foundation-data']==3 and rows['model-cache']==5
 assert before=={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}

def test_backup_plan_preserves_newest_generations_without_deleting(tmp_path):
 ps=[]
 for i in range(5):
  p=_backup_generation(tmp_path/f'b{i}',str(i));p.chmod(0o700);import os;os.utime(p,(i,i));ps.append(p)
 removable=backup_generation_plan(ps,keep=3)
 assert [p.name for p in removable]==['b1','b0'] and all(p.exists() for p in ps)

def test_external_surfaces_never_claim_foundation_cleanup():
 for key in ('llama-log','toolhive-log','docker','model-cache','search-index'):
  assert RULES[key].disposition=='external-owner'

def _backup_generation(path,payload='x'):
 from ai_foundation.productization import FoundationConfig,backup
 source=path.parent/('.source-'+path.name);source.mkdir();(source/'x').write_text(payload)
 backup(FoundationConfig(str(source.resolve()),trace_file='x'),path)
 return path

def test_backup_retention_only_nominates_old_valid_excess(tmp_path):
 from ai_foundation.storage_lifecycle import backup_retention_plan
 import os
 ps=[]
 for i in range(5):
  p=_backup_generation(tmp_path/f'b{i}',str(i));os.utime(p,(i,i));ps.append(p)
 (ps[1]/'x').write_text('tampered')
 removable=backup_retention_plan(ps,keep=3)
 assert [x.name for x in removable]==['b0'] and all(x.exists() for x in ps)

def test_backup_retention_never_nominates_only_valid_backup(tmp_path):
 from ai_foundation.storage_lifecycle import backup_retention_plan
 good=_backup_generation(tmp_path/'good');bad=_backup_generation(tmp_path/'bad');(bad/'x').write_text('bad')
 assert backup_retention_plan([good,bad],keep=1)==()

def test_stale_artifact_plan_structurally_excludes_live_tree(tmp_path):
 from ai_foundation.storage_lifecycle import stale_artifact_plan
 live=tmp_path/'AI-Foundation';live.mkdir();inside=live/'.x.staging-a';inside.mkdir();stage=tmp_path/'.AI-Foundation.staging-old';stage.mkdir();q=tmp_path/'.AI-Foundation.failed-update';q.mkdir();other=tmp_path/'notes';other.mkdir()
 assert set(stale_artifact_plan([live,inside,stage,q,other],live))=={stage,q}

def test_backup_series_converges_and_protects_lkg(tmp_path):
 from ai_foundation.storage_lifecycle import backup_series_plan,apply_owned_directory_plan
 import os
 ps=[]
 for i in range(7):
  p=_backup_generation(tmp_path/f'foundation-backup-{i}',str(i));os.utime(p,ns=(i,i));ps.append(p)
 lkg=ps[1];plan=backup_series_plan(tmp_path,'foundation-backup-',keep=3,protected=(lkg,))
 assert lkg not in plan and {p.name for p in plan}=={'foundation-backup-0','foundation-backup-2','foundation-backup-3'}
 apply_owned_directory_plan(plan,tmp_path)
 remaining=[p for p in ps if p.exists()];assert len(remaining)==4 and lkg in remaining
 assert backup_series_plan(tmp_path,'foundation-backup-',keep=3,protected=(lkg,))==()

def test_owned_directory_apply_refuses_cross_owner_and_symlink(tmp_path):
 from ai_foundation.storage_lifecycle import apply_owned_directory_plan
 import pytest
 owner=tmp_path/'owner';owner.mkdir();outside=tmp_path/'outside';outside.mkdir();link=owner/'link';link.symlink_to(outside,target_is_directory=True)
 with pytest.raises(ValueError,match='outside owner'):apply_owned_directory_plan([outside],owner)
 with pytest.raises(ValueError,match='real directory'):apply_owned_directory_plan([link],owner)
 assert outside.exists()

def test_backup_maintenance_requires_explicit_run(tmp_path):
 from ai_foundation.storage_lifecycle import BackupMaintenance
 import os
 ps=[]
 for i in range(5):
  p=_backup_generation(tmp_path/f'foundation-backup-{i}',str(i));os.utime(p,ns=(i,i));ps.append(p)
 m=BackupMaintenance(tmp_path,keep=2)
 assert len(m.plan())==3 and all(p.exists() for p in ps) # observation/planning cannot mutate
 removed=m.run();assert len(removed)==3 and len([p for p in ps if p.exists()])==2
 assert m.plan()==()

def test_docker_inventory_never_marks_volumes_reclaimable():
 from ai_foundation.storage_lifecycle import classify_docker_inventory
 rows=classify_docker_inventory(images=({'id':'live','tags':['x']},{'id':'old','tags':['y']},{'id':'dang','tags':[]}),containers=({'image_id':'live','running':True},),volumes=({'name':'db','size':99},),build_cache=({'id':'c','size':5},))
 assert ('image','live','live',0) in rows and ('image','old','unused',0) in rows and ('image','dang','dangling',0) in rows
 assert ('volume','db','protected-persistent',99) in rows and ('build-cache','c','cache',5) in rows

def test_model_classification_protects_configured_and_separates_partial(tmp_path):
 from ai_foundation.storage_lifecycle import configured_model_artifacts,classify_model_files
 live=tmp_path/'model.gguf';live.write_text('x');old=tmp_path/'old.gguf';old.write_text('x');part=tmp_path/'new.gguf.incomplete';part.write_text('x')
 cfg=f'models:\n  a:\n    cmd: llama --model "{live}" --port 1\n'
 configured=configured_model_artifacts(cfg);rows=dict(classify_model_files([live,old,part],configured))
 assert rows[live]=='configured-live' and rows[old]=='cache-unreferenced' and rows[part]=='partial-download'

def test_model_cleanup_disposable_tree_preserves_configured_and_rejects_symlink(tmp_path):
 from ai_foundation.storage_lifecycle import model_cleanup_plan,apply_owned_file_plan
 import pytest
 root=tmp_path/'cache';root.mkdir();live=root/'live.gguf';live.write_text('live');old=root/'old.gguf';old.write_text('old');part=root/'x.incomplete';part.write_text('part');outside=tmp_path/'outside';outside.write_text('x');link=root/'link';link.symlink_to(outside)
 plan=model_cleanup_plan([live,old,part,link],configured=(live,));assert set(plan)=={old,part}
 apply_owned_file_plan(plan,root);assert live.exists() and outside.exists() and not old.exists() and not part.exists()
 with pytest.raises(ValueError):apply_owned_file_plan([link],root)

def test_docker_cleanup_plan_cannot_include_live_images_or_volumes():
 from ai_foundation.storage_lifecycle import classify_docker_inventory,docker_cleanup_plan
 rows=classify_docker_inventory(images=({'id':'live','tags':['a']},{'id':'old','tags':['b']},{'id':'d','tags':[]}),containers=({'image_id':'live','running':True},),volumes=({'name':'authority','size':100},),build_cache=({'id':'cache1','size':20},))
 plan=docker_cleanup_plan(rows);assert set(plan)=={('image','old'),('image','d'),('build-cache','cache1')};assert all(x[0]!='volume' for x in plan)

def test_hf_layout_cleanup_preserves_configured_blob_and_metadata(tmp_path):
 from ai_foundation.storage_lifecycle import configured_model_artifacts,model_cleanup_plan,apply_owned_file_plan
 repo=tmp_path/'hub'/'models--owner--model';blob=repo/'blobs'/'livehash';blob.parent.mkdir(parents=True);blob.write_text('live')
 snap=repo/'snapshots'/'rev';snap.mkdir(parents=True);link=snap/'model.gguf';link.symlink_to(blob)
 refs=repo/'refs';refs.mkdir();(refs/'main').write_text('rev')
 old=repo/'blobs'/'oldhash';old.write_text('old');partial=repo/'blobs'/'new.incomplete';partial.write_text('partial')
 cfg=f'models:\n  x:\n    cmd: llama --model "{blob}"\n';configured=configured_model_artifacts(cfg)
 plan=model_cleanup_plan([blob,old,partial,link,refs/'main'],configured)
 # Snapshot symlink/ref metadata are not regular unreferenced blob candidates.
 assert set(plan)=={old,partial,refs/'main'}
 # Owner adapter must scope cleanup to blobs, never repository metadata.
 blob_plan=tuple(p for p in plan if p.parent==repo/'blobs')
 apply_owned_file_plan(blob_plan,repo/'blobs')
 assert blob.exists() and link.resolve()==blob.resolve() and (refs/'main').read_text()=='rev'
 assert not old.exists() and not partial.exists()

def test_file_tree_status_streams_high_count_and_detects_fanout(tmp_path):
 from ai_foundation.storage_lifecycle import file_tree_status
 d=tmp_path/'many';d.mkdir()
 for i in range(1200):(d/f'f{i}').write_text('x')
 s=file_tree_status(tmp_path,warn_files=2000,warn_largest_dir=1000)
 assert s['files']==1200 and s['largest_dir_files']==1200 and not s['ok']

def test_file_tree_status_does_not_follow_symlink_tree(tmp_path):
 from ai_foundation.storage_lifecycle import file_tree_status
 outside=tmp_path/'outside';outside.mkdir();(outside/'x').write_text('x');root=tmp_path/'root';root.mkdir();(root/'link').symlink_to(outside,target_is_directory=True)
 assert file_tree_status(root)['files']==0

def test_index_source_ratio_flags_divergence_without_mutation():
 from ai_foundation.storage_lifecycle import index_source_ratio
 assert index_source_ratio(100,200)['ok']
 assert not index_source_ratio(100,500)['ok']
 assert index_source_ratio(0,0)['ok'] and not index_source_ratio(0,1)['ok']
