"""Run checks with default DB/cache paths redirected to a disposable directory."""
import os
import sys
import tempfile
from pathlib import Path

os.environ['UOIG_FORCE_SQLITE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import src.config as config
original = config.load_config
with tempfile.TemporaryDirectory(prefix='uoig-coverage-tests-') as folder:
    def isolated(path=None):
        cfg = original(path)
        if path is None:
            cfg['database'] = str(Path(folder) / 'default.db')
        return cfg
    config.load_config = isolated
    import pytest
    raise SystemExit(pytest.main(sys.argv[1:] or ['-q']))
