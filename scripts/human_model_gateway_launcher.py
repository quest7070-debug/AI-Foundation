"""Keep the existing gateway and replace only its CSRF lookup helper."""
import hashlib
import importlib.util
import json
from pathlib import Path
import runpy
import sys

def main():
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'runtime.json').read_text())
    gateway=manifest['gateway']
    script=Path(gateway['script'])
    if hashlib.sha256(script.read_bytes()).hexdigest()!=gateway['script_sha256']:
        raise RuntimeError('gateway source changed')
    helper=root/'scripts/gateway_support.py'
    if hashlib.sha256(helper.read_bytes()).hexdigest()!=manifest['files']['scripts/gateway_support.py']:
        raise RuntimeError('gateway helper changed')
    sys.path.insert(0,str(script.parent.parent/'src'))
    spec=importlib.util.spec_from_file_location('gateway_support',helper)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    sys.modules['gateway_support']=module
    sys.modules['scripts.gateway_support']=module
    sys.argv=[str(script),*sys.argv[1:]]
    runpy.run_path(str(script),run_name='__main__')

if __name__=='__main__':main()
