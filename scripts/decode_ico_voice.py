"""Decode Unicom voice remote FC groups to WAV via the iFLYTEK ICO codec.

已验证结论（2026-09-16）：
- FC 音频帧编码为讯飞 ICO（"讯飞16倍压缩"）：16 kHz 单声道 16-bit PCM，每 20 ms 一帧，
  压缩帧固定 40 字节（640 字节 PCM，压缩比 16:1）。内部为改造过的 Siren7/MLT 方案，
  帧内含 u16 置换与逐 u16 XOR 0x416 的混淆层。
- 48 字节组内容布局：[0..39] ICO 帧 | [40..41] u16 小端能量/VAD 指标（实测 0..29）
  | [42..43] 组序号（小端，重复头部分片号）| [44..47] 重复偏移 28..31 的内容。
- 本脚本不内置厂商代码：需要从 xiri.zip（讯飞语音助手插件）提取 libicocodec.so，
  用 Unicorn (ARM/Thumb) 模拟其导出的 initCodec/ICODecoder/ICOReset 完成解码。

用法：
  python scripts/decode_ico_voice.py --so .local/xiri/libicocodec.so

输入 data/derived/groups.jsonl，输出 .local/decoded/*.wav。
依赖：pip install unicorn numpy（libicocodec.so 为 32 位 ARM ELF，无需匹配主机架构）。
"""
from __future__ import annotations

import argparse
import json
import struct
import wave
from pathlib import Path

import numpy as np
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import (
    UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_SP,
)
from elftools.elf.elffile import ELFFile

# libicocodec.so 1.0.0 内部偏移（与该 .so 绑定，见 .so 的 SHA-256 校验）
OFF_INIT_CODEC = 0x2F25  # initCodec(r0, r1, flags)：bit0 编码器，bit1 解码器
OFF_ICO_DECODER = 0x5681  # ICODecoder(state, in, in_halfwords, out, out_len*)
OFF_ICO_RESET = 0x5791  # ICOReset(state)
ICO_MAGIC = 0x20150415
SAMPLE_RATE = 16000
FRAME_BYTES = 40
FRAME_PCM = 640

# GOT 槽位（.rel.plt）
GOT = {
    "memset": 0xBFE4, "memcpy": 0xBFF4, "_Znaj": 0xBFE0,
    "__cxa_atexit": 0xBFD8, "__cxa_finalize": 0xBFDC, "raise": 0xBFE8,
    "abort": 0xBFF0, "__gnu_Unwind_Find_exidx": 0xBFEC,
    "__cxa_begin_cleanup": 0xBFF8, "__cxa_type_match": 0xBFFC,
}


class IcoDecoder:
    """用 Unicorn 模拟 libicocodec.so 的解码路径。"""

    BASE = 0x100000

    def __init__(self, so_path: str | Path):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        uc = self.uc
        with open(so_path, "rb") as f:
            elf = ELFFile(f)
            for ph in elf.iter_segments():
                if ph.header.p_type != "PT_LOAD":
                    continue
                vaddr, data, memsz = ph.header.p_vaddr, ph.data(), ph.header.p_memsz
                start = (self.BASE + vaddr) & ~0xFFF
                end = (self.BASE + vaddr + max(memsz, len(data)) + 0xFFF) & ~0xFFF
                uc.mem_map(start, end - start)
                uc.mem_write(self.BASE + vaddr, data)
            # 无符号 GLOB_DAT/REL32 重定位按基址平移
            for rs in (".rel.dyn", ".rel.plt"):
                rel_sec = elf.get_section_by_name(rs)
                if not rel_sec:
                    continue
                for rel in rel_sec.iter_relocations():
                    if rel["r_info_sym"] == 0 and rel["r_info_type"] in (21, 23):
                        off = rel["r_offset"]
                        (val,) = struct.unpack("<I", uc.mem_read(self.BASE + off, 4))
                        uc.mem_write(self.BASE + off, struct.pack("<I", (val + self.BASE) & 0xFFFFFFFF))

        # libc 桩：分配区 + 栈 + 输入/输出缓冲
        self.STUB = 0xF0000000
        uc.mem_map(self.STUB, 0x1000)
        self.heap_base = 0xF1000000
        self.heap = self.heap_base
        uc.mem_map(self.heap, 0x100000)
        uc.mem_map(0xE0000000, 0x100000)
        self.addr2name = {}
        for i, (name, got) in enumerate(GOT.items()):
            addr = self.STUB + i * 8 + 4
            uc.mem_write(addr, struct.pack("<H", 0x4770))  # bx lr
            uc.mem_write(self.BASE + got, struct.pack("<I", addr))
            self.addr2name[addr] = name
        uc.hook_add(UC_HOOK_CODE, self._stub)
        self.MAGIC_RET = 0x80000000
        uc.mem_map(0xD0000000, 0x20000)
        self.IN, self.OUT = 0xD0000000, 0xD0010000
        self._init_decoder()

    def _stub(self, uc, address, size, user_data):
        name = self.addr2name.get(address)
        if not name:
            return
        r0 = uc.reg_read(UC_ARM_REG_R0)
        r1 = uc.reg_read(UC_ARM_REG_R1)
        r2 = uc.reg_read(UC_ARM_REG_R2)
        if name == "memset":
            uc.mem_write(r0, b"\x00" * r2)
            uc.reg_write(UC_ARM_REG_R0, r0)
        elif name == "memcpy":
            uc.mem_write(r0, bytes(uc.mem_read(r1, r2)))
            uc.reg_write(UC_ARM_REG_R0, r0)
        elif name == "_Znaj":  # operator new[]
            self.heap = (self.heap + 0xF) & ~0xF
            uc.reg_write(UC_ARM_REG_R0, self.heap)
            self.heap += r0 + 16
        else:
            uc.reg_write(UC_ARM_REG_R0, 0)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    def _call(self, addr, args):
        uc = self.uc
        sp = 0xE0080000 - 0x200
        for i, a in enumerate(args[:4]):
            uc.reg_write(UC_ARM_REG_R0 + i, a)
        for i, a in enumerate(args[4:]):
            uc.mem_write(sp + i * 4, struct.pack("<I", a))
        uc.reg_write(UC_ARM_REG_SP, sp)
        uc.reg_write(UC_ARM_REG_LR, self.MAGIC_RET)
        uc.emu_start(addr, self.MAGIC_RET, count=50_000_000)
        return uc.reg_read(UC_ARM_REG_R0)

    def _init_decoder(self):
        # initCodec 的 flags bit1：仅初始化解码器
        self._call(self.BASE + OFF_INIT_CODEC, [0, 0, 2])
        # 解码器状态句柄不落在固定字面量上，直接按 config 特征扫描全局区：
        # config = {buf, 5000, 16000, u16 7000}，句柄存在 config-0x1C+4 处
        scan = self.uc.mem_read(self.BASE + 0xC000, 0x400)
        for i in range(0, 0x3F0, 4):
            buf, size, rate = struct.unpack_from("<III", scan, i)
            bw = struct.unpack_from("<H", scan, i + 0xC)[0]
            if size == 5000 and rate == 16000 and bw == 7000 and buf >= self.heap_base:
                self.handle = struct.unpack(
                    "<I", self.uc.mem_read(self.BASE + 0xC000 + i - 0x18, 4))[0]
                break
        else:
            raise RuntimeError("initCodec 后未找到解码器状态（.so 版本不匹配？）")
        magic = struct.unpack("<I", self.uc.mem_read(self.handle, 4))[0]
        if magic != ICO_MAGIC:
            raise RuntimeError(f"状态 magic 不符: 0x{magic:08x}")

    def reset(self):
        """每次按下语音键开始新录音时，设备端编码器重新起帧；宿主端应等价复位。"""
        self._call(self.BASE + OFF_ICO_RESET, [self.handle])

    def decode_frame(self, frame: bytes) -> bytes:
        if len(frame) != FRAME_BYTES:
            raise ValueError(f"ICO 帧必须为 {FRAME_BYTES} 字节，得到 {len(frame)}")
        # 解码器会按 20 个 u16（40 字节）做 XOR，多写 88 字节防越界
        self.uc.mem_write(self.IN, bytes(frame) + b"\x00" * 88)
        rc = self._call(self.BASE + OFF_ICO_DECODER,
                        [self.handle, self.IN, FRAME_BYTES // 2, self.OUT, self.IN + 0x100])
        if rc != 0:
            raise RuntimeError(f"ICODecoder rc={rc}")
        return bytes(self.uc.mem_read(self.OUT, FRAME_PCM))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--so", required=True, help="libicocodec.so 路径（xiri.zip 内提取，勿提交）")
    ap.add_argument("--groups", default="data/derived/groups.jsonl")
    ap.add_argument("--outdir", default=".local/decoded")
    args = ap.parse_args()

    groups = [json.loads(line) for line in open(args.groups, encoding="utf-8")]
    dec = IcoDecoder(args.so)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    segs: dict[str, bytearray] = {}
    prev = None
    for g in groups:
        if g["label"] != prev:
            dec.reset()
            prev = g["label"]
            segs.setdefault(g["label"], bytearray())
        segs[g["label"]] += dec.decode_frame(bytes.fromhex(g["joined_content_hex"])[:40])

    for label, data in segs.items():
        wav = outdir / f"{label}.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(bytes(data))
        dur = len(data) / 2 / SAMPLE_RATE
        print(f"{wav}  {dur:.2f}s")


if __name__ == "__main__":
    main()
