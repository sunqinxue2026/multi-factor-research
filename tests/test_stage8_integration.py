import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    env = os.environ.copy()
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    return subprocess.run([sys.executable, '-I', '-X', 'utf8', str(ROOT/'scripts'/'run_stage8.py'), *map(str,args)], cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf-8', timeout=120)


def test_end_to_end_reproducible_and_refuses_overwrite(tmp_path):
    a, b = tmp_path/'a', tmp_path/'b'
    for target in (a,b):
        result = run('--output',target)
        assert result.returncode == 0, result.stderr
    first = json.loads((a/'summary.json').read_text(encoding='utf-8'))
    second = json.loads((b/'summary.json').read_text(encoding='utf-8'))
    assert first['counts']['market'] == 1500
    assert first['counts']['orders'] == first['counts']['trades'] == 41
    assert first['metrics']['final_equity'] == pytest.approx(86294.93)
    assert first['input_sha256'] == second['input_sha256']
    assert first['metrics'] == second['metrics']
    for name in ['daily_ic.csv','target_weights.csv','trades.csv','equity_curve.csv']:
        assert (a/name).read_bytes() == (b/name).read_bytes()
    assert run('--output',a).returncode != 0


def test_external_csv_short_sample_and_argument_contract(tmp_path):
    args = ['--csv',ROOT/'data/test/synthetic_market.csv', '--metadata',ROOT/'data/test/synthetic_metadata.json',
            '--calendar',ROOT/'data/test/synthetic_calendar.csv','--calendar-source','synthetic/calendar','--calendar-version','v1']
    result = run(*args,'--output',tmp_path/'external')
    assert result.returncode == 0, result.stderr
    summary = json.loads((tmp_path/'external/summary.json').read_text(encoding='utf-8'))
    assert summary['counts']['market'] == 6
    assert summary['counts']['trades'] == 0
    assert summary['metrics']['final_equity'] == 100000
    assert run('--csv',args[1],'--output',tmp_path/'bad').returncode != 0
