import pytest
from ai_foundation.developer_boundary import DeveloperAuthority
from ai_foundation.protected_resources import ProtectedResources
def test_developer_cannot_mutate_model_control_plane(tmp_path):
 m=tmp_path/'models';d=DeveloperAuthority(ProtectedResources((str(m),)))
 assert d.authorize_write(tmp_path/'repo'/'x.py')
 for x in (m/'weight.gguf',m/'llama-swap.yaml'):
  with pytest.raises(PermissionError):d.authorize_write(x)
 for a in ('fine_tune_model','model_switch','model_register'):
  with pytest.raises(PermissionError):d.authorize_action(a)
