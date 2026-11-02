"""Load the exact pool successor gate before frozen historical contracts."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'powpow_pool_stability_release', ROOT / 'scripts/powpow_pool_stability_release.py')
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
