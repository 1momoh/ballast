"""Host-authenticated REST: planning and history only; no cleanup/approval endpoint."""
import importlib.util
from pathlib import Path
import sys

from fastapi import APIRouter

_root = Path(__file__).resolve().parents[1]
_name = 'ballast_dashboard_package'
if _name not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_name, _root / '__init__.py', submodule_search_locations=[str(_root)])
    _package = importlib.util.module_from_spec(_spec)
    sys.modules[_name] = _package
    _spec.loader.exec_module(_package)
_package = sys.modules[_name]
router = APIRouter()


@router.get('/status')
def status():
    return _package.request('status', {})


@router.post('/scan')
def scan():
    return _package.request('scan', {})


@router.post('/plan')
def plan(body: dict):
    return _package.request('plan', body)


@router.post('/preview')
def preview(body: dict):
    if set(body) != {'plan_token'}:
        return dict(ok=False, error=dict(code='invalid', message='Expected plan_token only.'))
    return _package.request('apply', {**body, 'dry_run': True})
