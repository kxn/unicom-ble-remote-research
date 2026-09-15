# 联通 BLE 语音遥控器协议研究

研究一只无外壳型号的中国联通 BLE + 红外语音遥控器：已完成按键映射，找到触发语音相关数据流的方法，尚未解出可懂语音。

**这是独立的 PC 侧协议研究仓库。** CH582F / 小米遥控器产品项目是 [mi-remote-usb-bridge](https://github.com/kxn/mi-remote-usb-bridge)，本仓库不包含其固件或产品协议。

## 当前状态（2026-09-15）

| 项目 | 实测结果 |
| --- | --- |
| 设备 | 联通BLE语音遥控器；软件 `XFRSD0D_U_R01_846_40091`，硬件 `V1.2` |
| BLE 服务 | 1800、1801、180A、180F、1812、FD00；未发现小米的 AB5E ATVV 服务 |
| 按键 | 29 个键中的 28 个有 BLE HID 输出；包括红色电源。TV 键未观察到 HID 输出，红外尚未验证 |
| 语音按键 | HID F8：按下 `82 03 01`、松开 `82 03 00`，各补零到 20 字节；另有键盘 EA 报告 |
| 启动实验 | 按下语音键后，向 HID FB（ATT value handle `0x0038`）写单字节 `01`，FC（`0x0034`）开始连续传输；两次成功 |
| 已保存数据 | 1188 个 FC 通知，396 组，每组 3 个 20 字节通知；约每 20 ms 一组，序号连续 |
| 停止 | 松手时写 `00` 后数据流停止；尚未隔离验证“仅写 00”和“仅松手”的各自作用 |
| 解码 | **未完成**。用户试听过的一个 Opus 候选只有噪声；其他候选也没有通过可懂语音验证 |

范围仅限这只样机。不能凭“联通/移动/电信遥控器”外观推广为通用协议；当前也不能给芯片厂家或音频编码下定论。

## 目前卡在哪里

1. **最小握手尚需隔离。** 两次 FB 成功发生在同一连接，之前写过 FA，并订阅了 FD02；需要新连接、不写 FA 的对照，再检查 FD02 是否必要。
2. **分包已识别，音频边界未识别。** 通知前 4 字节是小端组序号和分片号；第三片尾部包含重复序号、重复数据，不能把剩余 48 字节全部当音频。
3. **编码未知。** 广电报批稿列 SBC 必选、ADPCM/Opus/L2HC 可选，但本机报告 ID、控制报文、序号结构都不匹配该稿，不能直接套用。
4. **缺少原主机参考。** 用户现有盒子只有红外，没有蓝牙；需要依靠主动实验、数据分析和公开 SDK。

## 资料导航

- [讯飞 / Realtek 编码与报文资料补充（2026-09-16）](docs/iflytek-realtek-sources.md)
- [详细语音进展、失败候选、广电文档对照](docs/unicom-voice-investigation.md)
- [下一步实验顺序](docs/next-experiments.md)
- [29 键映射](docs/unicom-keymap.md) / [机器可读键表](docs/unicom-keymap.json)
- [Windows 描述、GATT 表与实时访问历史](docs/unicom-ble-investigation.md)
- [原始证据说明](docs/evidence.md)
- [环境搭建与捕获操作](docs/setup.md)

## 快速离线复核

只需 Python 标准库，无需连接遥控器：

```powershell
python scripts/analyze_capture.py docs/unicom-voice-evidence.jsonl
```

应得到 1188 个数据包、396 个完整组、0 个组内缺片、0 次组序号跳变；尾部重复字段匹配 396/396。

## 实时实验入口

使用 WinUSB 外接 `0A12:0001` 蓝牙棒和 Bumble，在 Windows 用户态控制 BLE；原机内置蓝牙无需修改。虚拟环境、密钥、下载和新录音均留在本仓库的忽略目录。

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe scripts/voice_probe.py --help
```

完整操作见 [setup.md](docs/setup.md)。默认只监听；业务写入通过明确的一次性实验指令触发。现有 handle 只适用于已识别样机，脚本会核对关键 Report Reference。
