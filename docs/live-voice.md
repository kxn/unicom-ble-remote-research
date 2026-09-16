# PC 实时语音通路

通路：WinUSB 蓝牙棒 → Bumble GATT → FC 分片重组 → 原生 ICO 解码器 → 16 kHz / 单声道 / 16-bit WAV。

## 构建与运行

在仓库根目录执行：

```powershell
.venv/Scripts/python.exe scripts/ico_decoder/build.py
.venv/Scripts/python.exe -m unittest discover -s tests -v
.venv/Scripts/python.exe scripts/voice_probe.py --record-voice
```

构建脚本使用原生 GCC/Clang，可通过 `--cc <编译器路径>` 指定；Windows 优先检测 `C:/msys64/mingw64/bin/gcc.exe`。参考源码逐个校验 SHA-256，DLL 和离线 demo 写入 `.local/ico/`。此通路不依赖厂商库或 ARM 模拟。

看到 `listening` 后，按住语音键说话，松手后等待 `audio_saved`，再开始下一段。单次录音最多 8 秒。若唤醒不能连接，需进入遥控器配对模式。

`--record-voice` 是明确启用语音业务写入的开关：每次按下 F8 语音键后向 FB 写 `01`，松手或超时写 `00`。默认不带该参数时，仍是原来的被动监听/手动排队实验模式。录音模式只接受队列中的 `stop`，不混入 FA 实验。

```powershell
.venv/Scripts/python.exe scripts/queue_command.py stop
```

停止会完成当前录音的停止命令和尾包处理，然后断开。使用自定义 `--work-dir` 时，排队脚本也要指定同一个目录。

## 输出与判据

- `.local/session/voice-<时间>.jsonl`：原始通知、开始/停止写入、录音结果及连接事件。
- `.local/session/audio/ico_<时间>_<编号>.wav`：每次按键独立一段，开始时重置 ICO 状态。
- WAV 同名 `.json`：帧数、包数、时长、错误列表和 `valid`。

收到每组三个 20 字节 FC 通知后，核对分片顺序、连续序号、尾部重复字段；取重组内容前 40 字节，实时解出 320 个 PCM 样本。松手写停止后等待至少 300 ms 无新包，尾包等待最多 1 秒。

缺片、乱序、重复片、跳号、异常长度或尾部、断连及业务写入失败，会标记录音无效；保留已解出的部分 WAV 和原始日志，不做未经验证的丢包补偿。`valid` 仅表示收包/解码通路检查通过，最终仍需试听确认内容。没有收到音频的空录音也会标记无效。

## 回归范围

`tests/test_voice_audio.py` 用已保存的 396 组数据经过实时模块，逐字节对照原有离线 C demo；同时验证每轮状态重置、缺片/重复/乱序/异常长度、尾包不完整、空录音、序号跳变与 16-bit 回绕、尾部字段损坏。

原始数据不作修改，厂商二进制、配对密钥和新录音留在忽略目录。新录音需要单独试听；离线回归不替代真实设备测试。

## 实机验证（2026-09-16）

新连接配对成功、订阅全部通知并核对 FC/FB/F8/FA Report Reference 后，未写 FA，连续完成两轮按键录音：

| 录音 | FC 通知 | ICO 帧 | WAV 时长 | 结果 |
| --- | ---: | ---: | ---: | --- |
| `ico_1789524775_001` | 609 | 203 | 4.06 s | 无缺片/跳号；用户试听确认内容、速度和音调正常 |
| `ico_1789524775_002` | 396 | 132 | 2.64 s | 无缺片/跳号；用户试听确认内容、速度和音调正常 |

原始记录为本地 `.local/session/voice-1789524775.jsonl`，音频及结果 JSON 在 `.local/session/audio/`。两次 FB 的 `01` / `00` 均得到 ACK。第二轮在停止写入后仍有最后一组音频到达，已由尾包等待接收。

将本轮原始 JSONL 再独立重组并交给离线 C demo，生成的两份 WAV 与实时输出整个文件逐字节一致：合计 1005 个通知、335 个完整组，0 个缺片、0 次序号跳变。测试后通过 `queue_command.py stop` 正常断开。

WAV 文件 SHA-256（用于核对这次试听文件）：

```text
001: 92a54f7be487909dd0983560d0b432d819771e8bcdcc3a9cb850812910bc3426
002: 72de1ce888f0a96045bb69d28249515cfde40f5c4a3a57b20d5e95ff6a976d37
```

本轮证实：在当前配对和全通知订阅条件下，FA 预写不是启动语音的必要条件。FD02 是否必须订阅、主机 `00` 和松手是否分别能独立停止，仍未隔离；8 秒看门狗分支也未在本轮实机触发。
