"""Run after scripts/ico_decoder/build.py: python -m unittest discover -s tests."""
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from voice_audio import NativeIco, Recording, DEFAULT_LIBRARY

GROUPS = [json.loads(line) for line in (ROOT/'data/derived/groups.jsonl').read_text().splitlines()]

def packets(group, seq=None):
    seq = group['sequence'] if seq is None else seq
    content = bytearray.fromhex(group['joined_content_hex'])
    struct.pack_into('<H', content, 42, seq)
    return [struct.pack('<HH', seq, i)+content[i*16:(i+1)*16] for i in range(3)]

class AudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.decoder = NativeIco()
        self.recordings = []

    def tearDown(self):
        for rec in self.recordings:
            rec.finish()
        self.decoder.close()
        self.temp.cleanup()

    def record(self, name='test'):
        rec = Recording(self.decoder, self.root/(name+'.wav'))
        self.recordings.append(rec)
        return rec

    def test_all_captures_match_offline_demo(self):
        exe = DEFAULT_LIBRARY.parent/('ico_decoder.exe' if sys.platform=='win32' else 'ico_decoder')
        subprocess.run([str(exe), str(ROOT/'data/derived/groups.jsonl'), str(self.root/'baseline')], check=True, capture_output=True)
        previous = None
        results = []
        for group in GROUPS:
            if group['label'] != previous:
                if previous is not None:
                    results.append((previous, rec.finish()))
                previous = group['label']
                rec = self.record(previous)
            for packet in packets(group):
                rec.feed(packet)
        results.append((previous, rec.finish()))
        self.assertEqual(sum(r['frames'] for _, r in results), 396)
        for label, result in results:
            self.assertTrue(result['valid'], result)
            with wave.open(result['path'], 'rb') as w:
                self.assertEqual((w.getframerate(),w.getnchannels(),w.getsampwidth()), (16000,1,2))
                actual = w.readframes(w.getnframes())
            with wave.open(str(self.root/'baseline'/(label+'.wav')), 'rb') as w:
                self.assertEqual(actual, w.readframes(w.getnframes()))

    def test_missing_duplicate_order_and_length_are_rejected(self):
        p = packets(GROUPS[0])
        cases = [[p[0], p[2]], [p[0], p[0]], [p[1]], [p[0][:-1]]]
        for n, case in enumerate(cases):
            rec = self.record(str(n))
            for packet in case: rec.feed(packet)
            self.assertFalse(rec.finish()['valid'])
            self.assertEqual(rec.frames, 0)

    def test_incomplete_tail_and_empty_capture_are_rejected(self):
        rec = self.record('partial')
        rec.feed(packets(GROUPS[0])[0])
        self.assertIn('incomplete final group', rec.finish()['errors'])
        self.assertFalse(self.record('empty').finish()['valid'])

    def test_sequence_gap_is_rejected_and_wrap_is_valid(self):
        rec = self.record('gap')
        for seq in [1, 3]:
            for packet in packets(GROUPS[0], seq): rec.feed(packet)
        self.assertFalse(rec.finish()['valid'])
        rec = self.record('wrap')
        for seq in [65535, 0]:
            for packet in packets(GROUPS[0], seq): rec.feed(packet)
        self.assertTrue(rec.finish()['valid'])
        self.assertEqual(rec.frames, 2)

    def test_trailer_corruption_is_rejected(self):
        p = packets(GROUPS[0]); p[2] = p[2][:-1]+bytes([p[2][-1]^1])
        rec = self.record()
        for packet in p: rec.feed(packet)
        self.assertFalse(rec.finish()['valid'])

    def test_recording_resets_codec(self):
        data = []
        for name in ['first', 'second']:
            rec = self.record(name)
            for group in GROUPS[:10]:
                for packet in packets(group): rec.feed(packet)
            result = rec.finish()
            data.append(Path(result['path']).read_bytes())
        self.assertEqual(data[0], data[1])

if __name__ == '__main__':
    unittest.main()
