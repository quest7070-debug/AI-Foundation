from dataclasses import dataclass
from pathlib import Path

MODEL_SUFFIXES=frozenset({'.gguf','.safetensors','.bin','.pt','.pth','.ckpt'})
MODEL_CONTROL_NAMES=frozenset({'llama-swap.yaml','llama-swap.yml','modelfile','models.json','models.yaml','models.yml'})
TRAINING_MARKERS=('fine-tun','finetun','training','trainer','lora','qlora')

@dataclass(frozen=True)
class ProtectedResources:
    """Paths/actions that Developer/Agent FILES authority must never mutate."""
    roots: tuple[str,...]=()
    def normalized_roots(self):
        return tuple(str(Path(x).expanduser().resolve()) for x in self.roots)
    def protects_path(self,target):
        p=Path(target).expanduser().resolve()
        if p.suffix.lower() in MODEL_SUFFIXES or p.name.lower() in MODEL_CONTROL_NAMES:return True
        return any(p==Path(r) or Path(r) in p.parents for r in self.normalized_roots())
    def validate_scope(self,root,write):
        if write and self.protects_path(root):raise PermissionError('protected model/runtime resource cannot be write-scoped')
    def validate_write(self,target):
        if self.protects_path(target):raise PermissionError('protected model/runtime resource cannot be modified')
    def validate_action(self,action):
        a=action.lower().replace('_','-')
        if any(x in a for x in TRAINING_MARKERS) or ('model' in a and any(x in a for x in ('load','switch','register','replace','write','update'))):
            raise PermissionError('model training/registration/switch is not a Developer capability')

def production_protected_resources(data_dir):
    home=Path.home()
    return ProtectedResources((
        str(Path(data_dir)/'local-compute'),
        str(home/'.cache/huggingface'),
        str(home/'.cache/llama.cpp'),
        str(home/'.ollama/models'),
    ))
