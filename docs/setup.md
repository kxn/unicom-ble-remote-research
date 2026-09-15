# Windows 实验环境

已验证：Windows、USB `0A12:0001` 外接蓝牙棒、WinUSB、Bumble 0.0.234。适配器自报 CSR8510 A10 / HCI 4.0，实际扫描、加密配对、GATT 和通知均成功。

Zadig 只作用于该外接棒。原机内置 RZ616 保留 Windows 蓝牙驱动。切换后外接棒不再作为普通 Windows 蓝牙收发器使用，而由脚本经 USB HCI 控制。

参考：[Bumble Windows](https://google.github.io/bumble/platforms/windows.html)、[Bumble 硬件](https://google.github.io/bumble/hardware/index.html)、[Zadig](https://zadig.akeo.ie/)。

## 安装与监听

在本仓库根目录运行：

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -u scripts/voice_probe.py
```

脚本等待连接时，让遥控器进入配对模式（有限时）。默认目标 `0C:F3:DE:C6:AE:64/P`，不要与其他控制该 USB 棒的程序同时运行。仅方向键唤醒在此前不总能重连；重新进入配对模式成功率较高。

看到 `listening` 后可测试按键。默认订阅所有可通知特征，包括 FD02；没有指令时不发送业务写命令。

运行数据在 `.local/session/`，密钥为 `pairing-keys.json`。需要沿用旧本地密钥时，可以将 `.local/legacy-lab/pairing-keys.json` 复制到该目录；此前仍出现过遥控器忘记密钥的情况，不能保证省略重新配对。

## 单次 FB 实验

在另一个终端、同一仓库目录：

```powershell
python scripts/queue_command.py fb
```

看到捕获终端 `armed` 后，按住语音键并说话，随后松开。程序收到 F8 按下通知后向 FB 写 `01`，松手或最多 8 秒后写 `00`。每条队列指令只触发一次。

```powershell
python scripts/queue_command.py fa
```

上述命令复现 FA 对照实验，不是已验证的语音启动方法。

结束会话：

```powershell
python scripts/queue_command.py stop
```

队列文件用原子替换生成，避免捕获程序读到半写入 JSON。已有待处理文件时不覆盖。脚本启动发现旧队列会拒绝运行，需先检查并移走 `.local/session/voice-command.json`，避免重启后误执行旧实验。

更改运行目录时，在捕获与队列命令中同时指定 `--work-dir`。查看 `--help` 可见 USB 传输、目标地址等参数。脚本为样机探针，写操作前会核对 FB/FA/F8 的 Report Reference；不是通用 HID 语音驱动。

## 离线复核

```powershell
python scripts/analyze_capture.py docs/unicom-voice-evidence.jsonl
python scripts/analyze_capture.py docs/unicom-voice-evidence.jsonl --output .local/analysis
```

输出 `groups.jsonl` 保留每组各分片内容及其拼接结果。**拼接结果不是已确认的音频载荷**，不自动去尾、不指定编码、不生成声称可用的 WAV。
