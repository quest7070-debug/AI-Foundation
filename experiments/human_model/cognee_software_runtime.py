"""Keep optional software on the system volume; all HumanModel data stays external."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

def software_home():
    return Path.home()/'Library/Application Support/HumanModel/runtimes/cognee-1.6.5'

def runtime_python(data_root):
    home = software_home()
    marker = home/'complete.json'
    if marker.is_file():
        if home.is_symlink() or marker.is_symlink():
            raise PermissionError('symlinked software runtime')
        receipt = json.loads(marker.read_text())
        if receipt.get('version') != '1.6.5':
            raise ValueError('unexpected software runtime')
        python = home/'venv/bin/python'
        if not python.is_file(): raise RuntimeError('software runtime incomplete')
        return python
    return Path(data_root)/'tools/cognee-1.6.5/venv/bin/python'

def prepare_runtime(external_install):
    """Copy the already installed dependency set, not weights or personal data."""
    external_install = Path(external_install)
    requirements = (external_install/'installed-requirements.txt').read_bytes()
    fingerprint = hashlib.sha256(requirements).hexdigest()
    destination = software_home()
    current = Path.home()/'Library/Application Support'
    for part in ('HumanModel','runtimes','cognee-1.6.5'):
        current = current/part
        if current.is_symlink(): raise PermissionError('symlinked software directory')
        current.mkdir(mode=0o700,exist_ok=True)
    if str(destination.resolve()).startswith('/Volumes/'):
        raise RuntimeError('INTERNAL_SOFTWARE_LOCATION_REQUIRED')
    marker = destination/'complete.json'
    if marker.is_file():
        receipt = json.loads(marker.read_text())
        if receipt.get('requirements_sha256') != fingerprint:
            raise RuntimeError('SOFTWARE_DEPENDENCIES_CHANGED')
        return runtime_python(external_install.parent.parent)
    if shutil.disk_usage(Path.home()).free < 4*1024**3:
        raise RuntimeError('INTERNAL_SOFTWARE_SPACE_UNAVAILABLE')
    python = destination/'venv/bin/python'
    with (destination/'prepare-private.log').open('a') as log:
        if not python.is_file():
            subprocess.run([sys.executable,'-m','venv','--copies',str(destination/'venv')],
                           check=True,timeout=60,stdout=log,stderr=log)
        relative = Path('lib')/('python%d.%d'%sys.version_info[:2])/'site-packages'
        source = external_install/'venv'/relative
        target = destination/'venv'/relative
        if not source.is_dir(): raise RuntimeError('SOFTWARE_PYTHON_VERSION_MISMATCH')
        # A fresh venv supplies the interpreter and entry points. Wheel-installed
        # packages and native relative-library layouts retain the exact versions.
        shutil.copytree(source,target,dirs_exist_ok=True,symlinks=True)
        compiled = subprocess.run([str(python),'-m','compileall','-q',str(target)],
                                  timeout=300,stdout=log,stderr=log)
        checked = subprocess.run([str(python),'-c',
            'import importlib.metadata; assert importlib.metadata.version("cognee") == "1.6.5"'],
            check=True,timeout=30,stdout=log,stderr=log)
    receipt = {'version':'1.6.5','requirements_sha256':fingerprint,
               'python':list(sys.version_info[:2]),'bytecode_compiled':compiled.returncode==0,
               'contains_personal_data':False,'model_weights_copied':False}
    temporary = destination/'complete.tmp'
    temporary.write_text(json.dumps(receipt))
    os.replace(temporary,marker)
    return python
