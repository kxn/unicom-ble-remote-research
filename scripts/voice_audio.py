"""Native ICO decoding and strict FC reassembly for one recording at a time."""
import ctypes
import os
from pathlib import Path
import struct
import wave

DEFAULT_LIBRARY = Path(__file__).resolve().parents[1]/'.local/ico'/('ico.dll' if os.name == 'nt' else 'libico.so')

class NativeIco:
    def __init__(self, path=DEFAULT_LIBRARY):
        self.lib = ctypes.CDLL(str(Path(path).resolve()))
        self.lib.ico_create.restype = ctypes.c_void_p
        self.lib.ico_destroy.argtypes = [ctypes.c_void_p]
        self.lib.ico_destroy.restype = None
        self.lib.ico_restart.argtypes = [ctypes.c_void_p]
        self.lib.ico_restart.restype = ctypes.c_int
        self.lib.ico_decode.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        self.lib.ico_decode.restype = ctypes.c_int
        self.state = self.lib.ico_create()
        if not self.state:
            raise MemoryError('ico_create failed')

    def reset(self):
        if self.lib.ico_restart(self.state) != 0:
            raise RuntimeError('ICO reset failed')

    def decode(self, frame):
        if len(frame) != 40:
            raise ValueError('Expected 40-byte ICO frame')
        src = ctypes.create_string_buffer(frame)
        pcm = (ctypes.c_int16 * 320)()
        if self.lib.ico_decode(self.state, src, 40, pcm) != 320:
            raise RuntimeError('ICO decode failed')
        return struct.pack('<320h', *pcm)

    def close(self):
        if self.state:
            self.lib.ico_destroy(self.state)
            self.state = None

class Recording:
    def __init__(self, decoder, path):
        self.decoder = decoder
        decoder.reset()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Never silently replace an earlier recording.
        self.file = self.path.open('xb')
        self.wav = wave.open(self.file, 'wb')
        self.wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        self.sequence = None
        self.previous = None
        self.parts = []
        self.frames = 0
        self.packets = 0
        self.errors = []
        self.closed = False

    def fail(self, reason):
        if reason not in self.errors:
            self.errors.append(reason)

    def feed(self, packet):
        self.packets += 1
        if self.errors:
            return
        if len(packet) != 20:
            self.fail('unexpected FC length')
            return
        seq, part = struct.unpack_from('<HH', packet)
        if part != len(self.parts) or part > 2:
            self.fail('missing, duplicate or out-of-order fragment')
            return
        if part == 0:
            if self.previous is not None and seq != (self.previous + 1) & 65535:
                self.fail('group sequence discontinuity')
                return
            self.sequence = seq
        elif seq != self.sequence:
            self.fail('fragment sequence mismatch')
            return
        self.parts.append(packet[4:])
        if part == 2:
            content = b''.join(self.parts)
            if struct.unpack_from('<H', content, 42)[0] != seq or content[44:48] != content[28:32]:
                self.fail('unexpected group trailer')
                return
            self.wav.writeframesraw(self.decoder.decode(content[:40]))
            self.frames += 1
            self.previous = seq
            self.parts = []

    def finish(self):
        if self.parts:
            self.fail('incomplete final group')
        if not self.frames:
            self.fail('no audio frames')
        if not self.closed:
            self.wav.close()
            self.file.close()
            self.closed = True
        return dict(path=str(self.path.resolve()), frames=self.frames, packets=self.packets,
                    seconds=self.frames/50, sample_rate=16000,
                    valid=not self.errors, errors=list(self.errors))
