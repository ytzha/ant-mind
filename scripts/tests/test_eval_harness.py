import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
h = load('harness', 'scripts/eval-matrix-harness.py')
c = load('cleaner', 'scripts/eval-prompts/clean_dsl.py')

class HarnessTests(unittest.TestCase):
    def payload(self):
        return {'cells': [{'species': 'hauler', 'ticks': 300, 'label': 'candidate',
                           'dslSha256': 'abc', 'score': 10, 'selfcheck': {'passed': True}}],
                'determinism': {'enabled': True, 'passed': 1, 'total': 1, 'failed': 0}}
    def test_same_valid_payload(self):
        self.assertTrue(h.reconcile(self.payload(), self.payload())['passed'])
    def test_empty_cannot_pass(self):
        p = {'cells': [], 'determinism': {'enabled': True, 'total': 0, 'passed': 0, 'failed': 0}}
        self.assertFalse(h.reconcile(p, p)['passed'])
    def test_duplicate_key_cannot_pass(self):
        p = self.payload(); p['cells'] *= 2
        p['determinism'].update(total=2, passed=2)
        self.assertFalse(h.reconcile(p, p)['passed'])
    def test_bad_count_cannot_pass(self):
        p = self.payload(); p['determinism'].update(total=0, passed=0)
        self.assertFalse(h.reconcile(p, p)['passed'])
    def test_false_cell_cannot_pass(self):
        p = self.payload(); p['cells'][0]['selfcheck']['passed'] = False
        self.assertFalse(h.reconcile(p, p)['passed'])
    def test_difference_detected(self):
        a, b = self.payload(), self.payload(); b['cells'][0]['score'] = 11
        self.assertFalse(h.reconcile(a, b)['passed'])
    def test_crlf_hash_matches_bridge(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); src = p / 'src'; src.mkdir()
            data = b'wait();\r\n'; (src / 'x.ant').write_bytes(data)
            rows = h._freeze_copy_programs(src, p / 'dest')
            self.assertEqual((p / 'dest/x.ant').read_bytes(), data)
            self.assertEqual(rows[0]['dslSha256'], h.sha256_bytes(b'wait();\n'))
            self.assertEqual(rows[0]['fileSha256'], h.sha256_bytes(data))
    def test_actual_bridge_version(self):
        self.assertEqual(h.BRIDGE_VERSION, '0.2.1')
    def test_closed_then_open_thinking(self):
        raw = '<think>first</think>wait();\n<analysis>unfinished'
        self.assertEqual(c.clean_response(raw)['program'], 'wait();')
    def test_raw_preserved(self):
        raw = 'wait();\r\n'
        result = c.clean_response(raw)
        self.assertEqual(result['raw_response'], raw)
        self.assertEqual(result['rawSha256'], h.sha256_bytes(raw.encode()))
if __name__ == '__main__': unittest.main()
