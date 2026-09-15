# 联通 BLE 语音遥控器：Windows 描述检查（历史记录）

> 最新状态：已通过 FB 写入启动 FC 连续数据，编码尚未确定。见 [语音调查](unicom-voice-investigation.md)。以下初始缓存读取和早期无音频结论按实验阶段保留。

> 更新：已通过外接 USB 蓝牙棒 + Bumble 完成实时连接、配对、加密、HID Report Map 读取及按键通知捕获。下文最初的 Windows 访问限制仍属实，但已不再阻塞独立诊断。实测结果见文末。

> 逐键测试已完成：见 [29 键映射表](unicom-keymap.md)、[机器可读映射](unicom-keymap.json) 和 [原始通知证据](unicom-keymap-evidence.jsonl)。28 键确认 BLE HID 输出；TV 键未观察到 HID 输出，红外暂不测量。

初始缓存检查日期：2026-09-15。当时未修改板端代码、驱动或配对状态，未发送未知业务命令；后续驱动切换、配对及主动语音实验另有记录。

## 结论与证据边界

Windows 保存的服务表包含 HID（1812）及 FD00 扩展服务，没有小米 RC003 使用的 AB5E0001-5A21-4F05-BC7D-AF01F617B664 ATVV 服务。
因此可以确认设备声明了 HID，不能称为“只有 ATVV”，也不能直接沿用 RC003 的 ATVV 适配器。
FD00 的业务用途尚未确定；语音可能位于 HID 的厂商报表或扩展服务中，不能单凭 UUID 判定。

本次成功读取来自 Windows GATT 缓存。设备连接状态为 Disconnected；用户按方向键与语音键后，UNCACHED 服务查询仍返回 Unreachable。没有捕获到按键或音频数据。

## 设备自报信息

| 字段 | 值 |
| --- | --- |
| 名称 / 2A00 | 联通BLE语音遥控器 |
| 蓝牙地址 | 0C:F3:DE:C6:AE:64 |
| Appearance / 2A01 | 0x03C0 |
| 序列号 / 2A25 | 0613111410212445 |
| Firmware Revision / 2A26 | BLE5.0（只是字符串，不能据此验证链路版本） |
| Hardware Revision / 2A27 | V1.2 |
| Software Revision / 2A28 | XFRSD0D_U_R01_846_40091 |
| PnP ID / 2A50 | 01 16 04 00 03 10 01 |
| PnP 解码 | Source=1, VID=0x0416, PID=0x0300, Version=0x0110；不据此猜测实际芯片厂家 |
| 电池 / 2A19 | 缓存值 100% |

未取得厂商名或型号字符串。

## 缓存服务表

短 UUID 均使用基础 UUID `0000xxxx-0000-1000-8000-00805f9b34fb`。

| 服务起始 handle | UUID | 含义 |
| --- | --- | --- |
| 0x0001 | 1800 | GAP |
| 0x000C | 1801 | GATT |
| 0x0010 | 180A | Device Information |
| 0x001D | 180F | Battery |
| 0x0021 | 1812 | HID over GATT |
| 0x0049 | FD00 | 业务用途未确认 |

FD00 下可见特征（handle 为 WinRT GattCharacteristic.AttributeHandle 原值）：

- 0x004A / FD01：Write（0x08）。
- 0x004C / FD02：Write Without Response + Notify（0x14）。
- 0x004E / 2902：FD02 的 CCCD。

没有读取权限的特征不做试写。HID 特征枚举返回 AccessDenied，未取得 Report Map 或 Report Reference。

## Windows HID 失败原因

匹配该地址的 BTHLEDEVICE 1812 节点：

- ProblemCode：10（设备无法启动）。
- ProblemStatus：3221225657 / 0xC00000B9。
- DriverProblemDesc：`HID 报表描述符未通过验证。声明的非常量主项没有相应的用法。`
- 驱动：hidbthle.inf / Bluetooth Low Energy GATT compliant HID device。

这说明 Windows 拒绝了其 HID 描述符；按键在桌面无反应不能作为“按键只发红外”的证据。没有 Report Map 原始字节，尚不能定位具体错误项；这不是本项目固件的缺陷。

## 后续验证

先建立稳定 BLE 连接，再读取 HID Report Map/Reference 并监听输入报告与 FD02 通知，按键逐个对应。语音应在观察到握手及数据后才确定通道、编码及与 ATVV 的关系。若 Windows 继续限制 HID 访问，可使用独立 BLE Central 诊断环境；这一步与产品适配分开评估。

## 对照来源

- 项目 `firmware/adapters/rc003/rc003_adapter.c` 的 ATVV UUID 定义。
- [Google/Telink 遥控器参考 GATT 实现](https://android.googlesource.com/platform/hardware/telink/atv/refDesignRcu/+/refs/heads/master/vendor/827x_ble_remote/app_att.c)。
- [Bluetooth SIG Assigned Numbers](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/Assigned_Numbers/out/en/index-en.html)：FD00 的注册分配本身不代表本设备遵循何种语音协议，也不能代替流量验证。

## 公开资料检索补充

同日检索了联通/移动/电信语音遥控器逆向、协议、HID、SBC/ADPCM、FD00/FD01/FD02、设备软件标识 XFRSD0D 等组合。没有检索到与此设备标识匹配且已验证的接收器代码或完整逆向资料。搜索未命中不代表资料不存在。

有用的一手资料与对照：

1. [广电《机顶盒通用遥控技术要求和测量方法》报批稿](https://www.nrta.gov.cn/module/download/downfile.jsp?classid=0&filename=14c9ea36504347eeb7007b6774f0b737.pdf)：附录 D，PDF 第 49–52 页，明确规定 HID 语音数据/控制/通知报告 ID 为 0x30/0x31/0x32，并规定能力协商、START/AUDIOEND 边界及音频格式。可以作为识别候选，不能认定老款运营商设备必然遵循此报批稿，也不将其描述为现行正式标准。
2. [杰理 AW30N 官方遥控器应用文档](https://doc.zh-jieli.com/AW30/zh-cn/master/BLE_APP/ble_rc%26dongle/rc_app_introduction.html)：提供 BLE 遥控器/dongle、HID 键值与音频、编码队列及 ACK 控制流程的 SDK 入口。尚未找到与本机 FD00/软件版本的对应证据。
3. [scrool/qcar-docs](https://github.com/scrool/qcar-docs)：实测玩具车也有 FD00→FD01/FD02 结构，说明这组 UUID 本身不是语音专有指纹，不能据此断定 ATVV 或语音通道。
4. [ElectronicCats/jieli-ble-badge-research](https://github.com/ElectronicCats/jieli-ble-badge-research)：另一类设备将 FD00 用作 OTA。只说明存在其他用途，不代表本遥控器使用相同芯片或 OTA 协议。
5. [GTVBT1 厂商提交的用户手册](https://fcc.report/FCC-ID/2AV9UGTVBT1/4703682.pdf)：有 HID 键码、BLE 语音要求及 Google Android 9.0 语音说明，但没有本机匹配信息或可复用的完整报文协议。排除为直接适配依据。

下一步最省工作量的是获取外壳/电池仓型号或原配盒子型号，以此寻找 OEM 的 SDK/盒子接收端实现；设备可访问后只需优先比对 HID Report Reference 与候选协议，不必立即从音频流盲猜编码。

## Bumble 实时验证（同日）

### 接入环境

- 外接适配器：USB VID:PID `0A12:0001`，USB 自报 CSR8510 A10。
- 已由用户在 Zadig 将驱动切为 WinUSB，设备 ProblemCode=0，驱动 INF 为 oem17.inf。
- Bumble 0.0.234，传输 `usb:0A12:0001`。HCI 自报蓝牙 4.0、company_identifier=10、subversion=8891；支持 LE Encryption。实际 BLE 扫描成功。
- 实验环境与脚本：`build/ble-lab/venv/`、`probe.py`、`inspect_remote.py`，均在 Git 忽略的 build 目录。
- 原始记录：`build/ble-lab/remote-session.jsonl`。配对密钥单独保存在该目录内，不纳入文档或提交。
- 实时发现确认仅有 1800、1801、180A、180F、1812、FD00 六个服务，没有 AB5E ATVV 服务。
- Report Map 未加密读取返回 INSUFFICIENT_AUTHENTICATION；配对后链路 encryption=1，读取成功。
- 首次会话在 FD02 CCCD 订阅请求期间结束，原因未确定；下一次尝试复用密钥返回 PIN_OR_KEY_MISSING。再次配对后跳过 FD02 订阅，HID 通知成功。不能据此断定 FD02 导致断链。

### HID Report Reference

以下 handle 是实时 ATT 特征值 handle，不是 WinRT 特征声明 handle。

| 值 handle | Report ID | 类型 | Report Map 中载荷长度 |
| --- | --- | --- | --- |
| 0x002C | 01 | Input，键盘 | 8 字节 |
| 0x0030 | 03 | Input，Consumer | 2 字节 |
| 0x0034 | FC | Input，扩展 | 20 字节 |
| 0x0038 | FB | Output | Map 未声明 |
| 0x003B | F8 | Input，扩展 | 20 字节 |
| 0x003F | FA | Output | Map 未声明 |
| 0x0042 | F9 | Input，扩展 | 1 字节 |
| 0x0046 | 04 | Input，扩展 | 20 字节 |

Report Map 的 04/FC/F8/F9 集合都使用 Consumer Page，但 Input 项前缺少对应的局部 Usage/Usage Range；与 Windows 报错相符。此外，GATT 引用的 FB/FA Output 未在 Map 定义，Map 中 ID 01 的 LED Output 又没有对应的独立 Output Report Reference。这些是设备描述内部的不一致，不修改本项目来掩盖。

### 用户按键的实时通知

用户依次操作上、下、确定、按住语音后松开，观察到：

| 操作 | 值 handle / Report ID | ATT value（十六进制） |
| --- | --- | --- |
| 上 | 002C / 01 | 0000520000000000 |
| 下 | 002C / 01 | 0000510000000000 |
| 确定 | 002C / 01 | 0000280000000000 |
| 普通键松开 | 002C / 01 | 0000000000000000 |
| 语音按下 | 003B / F8 | 8203010000000000000000000000000000000000 |
| 语音按下，另一路 | 002C / 01 | 0000ea0000000000 |
| 语音松开 | 003B / F8 | 8203000000000000000000000000000000000000 |
| 语音松开，另一路 | 002C / 01 | 0000000000000000 |

因此普通键确实有 BLE HID 输出，语音键也通过 HID F8 报告状态。未收到音频流，不能确定语音数据使用 FC/F8/04 哪一个通道，也不能确定编码。FD00 的用途仍未确定。这不是已验证的 ATVV 实现。

当前进一步研究应优先寻找与 `F8:82 03 01/00`、FB/FA Output 配套的 HID 语音协议，探索逻辑可直接修改 PC Python 脚本，无需刷 CH582F。
