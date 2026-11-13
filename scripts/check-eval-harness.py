#!/usr/bin/env python3
"""Small real two-host harness smoke; no model calls or capability ranking."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def run(*args):
    subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, check=True)
def main():
    with tempfile.TemporaryDirectory(prefix='ant-harness-') as tmp:
        tmp = Path(tmp)
        run('scripts/eval-prompts/render_prompt.py', '--strategy', 's2', '--batch-id', 'smoke', '--out-root', tmp)
        batch = tmp / 'smoke'
        raw = batch / 'raw'; raw.mkdir()
        shutil.copyfile(ROOT / 'content/programs/hauler-reliable.ant', raw / 'official.txt')
        run('scripts/eval-prompts/clean_dsl.py', '--batch-dir', batch)
        run('scripts/eval-matrix-harness.py', 'run', '--request', batch / 'request.json',
            '--programs', batch / 'programs', '--run-id', 'smoke', '--out-root', tmp / 'runs',
            '--ticks', '300', '--species', 'hauler', '--review')
        report = json.loads((tmp / 'runs/smoke/harness.json').read_text(encoding='utf-8'))
        assert report['reconcile']['passed']
        assert all(x['matched'] for x in report['traceability']['dslLink'])
        assert report['verdict']['capabilityClaimAllowed'] is False
        assert report['traceability']['bridgeVersion'] == '0.2.1'
        print('PASS real render → clean → independent hosts → reconcile (not a model benchmark)')
if __name__ == '__main__': main()
