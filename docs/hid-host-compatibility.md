# Windows / macOS HID 兼容性观察

记录日期：2026-09-16。对象仅限软件 `XFRSD0D_U_R01_846_40091` 的样机。

## Windows：已观察到描述符校验失败

此前该设备的 Windows BLE HID 节点为 Code 10，ProblemStatus `0xC00000B9`，DriverProblemDesc 为：

> HID 报表描述符未通过验证。声明的非常量主项没有相应的用法。

完整历史见 [设备调查](unicom-ble-investigation.md)。原始 Report Map 为 [remote-session.jsonl](../data/raw/remote-session.jsonl) 第 36、113 行中 handle 42（`0x2A`，UUID `2A4B`）的 read 值，共 169 字节，两次读取一致。

逐项解析，以下 Input 均为 `81 00`（Data / Array / Absolute），但没有对应的局部 Usage 或 Usage 范围。偏移从 Report Map 第一个字节起按零计数：

| Report ID | Input 字节偏移 | 用途 |
| --- | --- | --- |
| 04 | 0x6A | 扩展输入 |
| FC | 0x7E | 语音数据 |
| F8 | 0x92 | 语音键状态 |
| F9 | 0xA6 | 扩展输入 |

FC 集合原始字节：

```text
05 0C       Usage Page (Consumer)
09 01       Usage (Consumer Control)
A1 01       Collection (Application)
85 FC       Report ID
95 14       Report Count (20)
75 08       Report Size (8)
15 00       Logical Minimum (0)
26 FF 00    Logical Maximum (255)
81 00       Input (Data, Array, Absolute)  ← 没有局部 Usage
C0          End Collection
```

`09 01` 被紧随其后的 Collection 使用；局部项目不会继承到下一个 Main item。`Usage Page` 只是类别，不能代替具体 Usage。因此上述缺陷与 Windows 错误直接对应。参见 [USB-IF HID 1.11](https://www.usb.org/sites/default/files/hid1_11.pdf) §6.2.2.8 和 [解析检查说明](https://www.usb.org/sites/default/files/documents/hidpar.pdf)。

另有描述内部不一致：GATT 存在 FB/FA Output Report Reference，Map 却未声明；Map 中 ID 01 的 LED Output 又无对应的独立 Output Report Reference。尚未做修正描述符后重交 Windows 的对照，不能保证只补 Usage 就解决全部问题。

## macOS：源码提示可能容忍，尚无实机结论

检查 Apple 官方 IOHIDFamily 开源代码，固定版本 `777ccd9698845aadf711e32d843c8c9b777431d9`：

- [IOHIDElementContainer.cpp](https://github.com/apple-oss-distributions/IOHIDFamily/blob/777ccd9698845aadf711e32d843c8c9b777431d9/IOHIDFamily/IOHIDElementContainer.cpp)：调用 `HIDOpenReportDescriptor` 时 flags 为 0。
- [HIDProcessReportItem.c](https://github.com/apple-oss-distributions/IOHIDFamily/blob/777ccd9698845aadf711e32d843c8c9b777431d9/IOHIDSystem/IOHIDDescriptorParser/HIDProcessReportItem.c)：没有看到“没有 Usage 即拒绝整个描述符”的分支；部分错误按 StrictErrorChecking 标志决定是否拒绝。
- [HIDGetButtonCaps.c](https://github.com/apple-oss-distributions/IOHIDFamily/blob/777ccd9698845aadf711e32d843c8c9b777431d9/IOHIDSystem/IOHIDDescriptorParser/HIDGetButtonCaps.c)：按 Usage 数量枚举按键能力，零 Usage 不生成相应按键能力。

**仅据这段实现推断**：macOS 可能跳过这些无法映射的扩展字段，仍让具有 Usage 的 01 键盘和 03 Consumer 报告工作。未实测本机在 Mac 上的配对、BLE HID 建立和按键事件；当前系统的 BLE 接入层可能还有其他校验，公开代码不能证明所有 macOS 版本都能用。

即便按键可用，私有 ICO 语音也不会因此自动变为系统麦克风；仍需启动命令、收包和解码程序。

## 是否故意限制电脑使用

没有足够证据认定厂商意图。以下观察更符合“面向配套盒子的私有实现，未做好通用 HID 兼容性”的解释，但它仍是推断：

- 普通按键的标准 Usage 存在，缺陷集中在扩展报告。
- 配对后按固定特征/Report ID 直接处理，可以取得按键和语音。
- 目前成功通路没有遇到额外的原厂主机身份认证。

“造成 Windows 不兼容”是实测结果；“故意防止电脑使用”不是已证实结论。即使将来在 Mac 实测成功，也只能说明系统容错存在差异，不能证明厂商动机。

CH582F 适配可直接解析已知 GATT 报告，再经自身正确的 USB 描述符及 RBP/3 通路输出；没有必要照搬本机有缺陷的 Report Map。移植尚未在本研究中实施。
