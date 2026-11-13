import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('freeze_data', Path(__file__).parents[1] / 'freeze_data.py')
freeze = importlib.util.module_from_spec(spec)
spec.loader.exec_module(freeze)


def test_snapshot_verifies_content_and_rejects_tampering(tmp_path):
    payload = tmp_path / 'fixture.csv'
    payload.write_text('unit-test-only payload\n')
    manifest = {'files': {'fixture.csv': {'sha256': freeze.sha256(payload)}}}
    (tmp_path / 'MANIFEST.json').write_text(json.dumps(manifest))
    assert freeze.verify(tmp_path) == manifest
    payload.write_text('changed unit-test payload\n')
    with pytest.raises(RuntimeError, match='hash mismatch'):
        freeze.verify(tmp_path)
