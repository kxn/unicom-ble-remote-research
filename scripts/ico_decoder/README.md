# ico_decoder — 纯 C 实现的联通遥控器语音解码器

不依赖厂商 `libicocodec.so` 和 Unicorn 模拟：直接把 **ITU-T G.722.1 定点参考解码器**
（7 kHz 模式，16 kbit/s）编译进来，外面套上从 `libicocodec.so` 逆向出的三层厂商封装：

1. **去混淆**：40 字节帧按小端 u16 重排（置换表 `ICO_PERM[20]`），再逐 u16 XOR `0x0416`；
2. **标准 G.722.1 解码**（MLT 变换，位流 MSB-first，320 bit/帧）；
3. **输出后处理**：每个 PCM 样本低 2 位清零（`& ~3`）。

状态语义与厂商实现一致：噪声填充 LCG 四种子 `{1,1,1,1}`，每次按下语音键（新的
`groups.jsonl` label）调用一次 `ico_reset()`；误差隐藏状态为 `old_coefs[280] +
old_mag_shift`，MLT 重叠相加历史为 `old_samples[160]`。

## 目录内容

| 文件 | 说明 |
| --- | --- |
| `ico_decoder.c` | 解码器主体：ICO 封装 + JSONL 解析 + WAV 输出 |
| `fetch_reference.py` | 下载 pjproject 打包的 G.722.1 参考实现（17 个文件），SHA-256 逐个校验 |
| `pj_shim/` | 最小 `pj/` 头文件垫片 + include 根目录（参考代码 include 形如 `"g7221/common/..."`） |

G.722.1 参考源码不入库，用 `fetch_reference.py` 拉取并哈希锁定（Polycom/ITU 定点参考，
经 pjproject `third_party/g7221` 分发；对应专利已到期）。

## 构建与运行

```powershell
python fetch_reference.py          # 生成 g7221/（已哈希校验，可重复执行）
cc -I pj_shim -I . -I g7221/common -I g7221/decode -o ico_decoder \
   g7221/common/basic_op.c g7221/common/common.c g7221/common/huff_tab.c \
   g7221/common/tables.c g7221/decode/coef2sam.c g7221/decode/dct4_s.c \
   g7221/decode/decoder.c ico_decoder.c
./ico_decoder ../../data/derived/groups.jsonl .local/decoded
```

任何 C89/C99 编译器均可（tcc、gcc、clang、MSVC cl 都行）。Windows 用 TinyCC 实测通过。

输入为 [data/derived/groups.jsonl](../../data/derived/groups.jsonl)（每行一个 48 字节组，
ICO 帧取 `joined_content_hex` 前 40 字节）；输出 `.local/decoded/<label>.wav`
（16 kHz 单声道 16-bit）。label 变化即认为新一轮录音，自动重置解码器状态。

## 验证

- **与厂商解码器逐样本比对**：用 Unicorn 模拟 `libicocodec.so`（见
  [scripts/decode_ico_voice.py](../decode_ico_voice.py)）解码全部 396 帧作为基准，
  本实现的输出 PCM **逐字节相同**（`fb_single_01_00` 157 帧、
  `fb_repeat_silence_speech` 239 帧，max|diff| = 0）。
- 解出的音频经 ASR 验证与实测说话内容一致（"一二三四五"→`1,2,3,4,5`；
  "现在测试联通遥控器"→`现在测试连通遥控器`），详见
  [语音调查](../../docs/unicom-voice-investigation.md)。

## 移植到其他项目

核心只有 `ico_reset()` / `ico_decode_frame()` 两个函数（约 40 行），加上 `IcoState`
结构体；把 `g7221/` 参考源码一起拷走即可脱离本仓库使用。逐帧调用约定：

```c
IcoState st;
ico_reset(&st);                        // 每次开始新录音时调用一次
int16_t pcm[320];
ico_decode_frame(&st, frame40, pcm);   // frame40 = 去混淆前的 40 字节 ICO 帧
```
