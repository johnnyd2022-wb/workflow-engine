"""Every model module must be importable on its own and leave a sortable schema.

A test or script that imports one model (the source-to-sale browser scenario imports only
SalesFifoAllocation, for example) must not hit NoReferencedTableError because the table a foreign key
points at lives in a module nothing else imported. That failure only shows in a fresh process, so each
module is imported in its own subprocess, a few at a time.
"""

import glob
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE = (
    "import importlib, sys\n"
    "importlib.import_module(sys.argv[1])\n"
    "from app.core.db.models.models import Base\n"
    "Base.metadata.sorted_tables\n"
)


def _model_modules():
    files = glob.glob("app/**/models/*.py", root_dir=ROOT, recursive=True)
    return sorted({f[:-3].replace(os.sep, ".") for f in files if not f.endswith("__init__.py")})


def _import_alone(module):
    env = {key: value for key, value in os.environ.items() if key != "ENVIRONMENT"}
    result = subprocess.run(
        [sys.executable, "-c", CODE, module], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120
    )
    return module, result.returncode, (result.stderr.strip().splitlines() or [""])[-1][:200]


def test_model_modules_found():
    assert len(_model_modules()) > 40


def test_every_model_module_imports_alone_and_sorts_the_schema():
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(_import_alone, _model_modules()))
    failures = [f"{module}: {error}" for module, code, error in results if code != 0]
    assert not failures, "model modules that fail when imported alone:\n" + "\n".join(failures)
