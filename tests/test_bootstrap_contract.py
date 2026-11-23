from pathlib import Path


def test_bootstrap_uses_frozen_lock_and_python_312():
    text = Path("scripts/bootstrap.sh").read_text()
    assert 'sync --frozen --python 3.12 --extra dev --extra remote' in text
    assert 'sys.version_info[:2] == (3, 12)' in text
    assert 'uv is required for frozen GitHub reconstruction' in text
