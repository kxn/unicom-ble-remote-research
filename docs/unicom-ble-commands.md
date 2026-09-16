# 联通遥控器 BLE 控制指令面：实测 + 厂商库逆向

日期：2026-09-16。两个来源必须分开标注：**实测**指对本机抓包验证过的行为；**厂商库**指对 xiri.zip 内 `libremote-control-jni.so` 等的反汇编结论（提取路径与哈希见[语音调查](unicom-voice-investigation.md)）。厂商库来自盒子生态，本机与其中 ListenAI 方案的对应关系是推断，不是已确证事实。

## 1. 实测确认的指令面（本机）

服务：`1800` GAP、`1801` GATT、`180A` DIS（软件标识 `XFRSD0D_U_R01_846_40091`）、`180F` BAS、`1812` HIDS、`FD00` 自定义服务。没有 ATVV（AB5E…）、没有 RTK voice（…0003FD）、没有 OTA 服务。

HIDS 报表面（逐键验证见[keymap](unicom-keymap.md)）：

| Report ID | 方向 | Page | 用途 | 格式 |
| --- | --- | --- | --- | --- |
| `01` | Input | `0x07` Keyboard | 28 个普通键 | 8 字节，`00 00 KK …` |
| `03` | Input | `0x0C` Consumer | 设置/首页/频道等 | 2 字节小端 usage |
| `F8` | Input（扩展） | Consumer | 语音键状态 | 20 字节，按下 `82 03 01`、松开 `82 03 00` |
| `FC` | Input（扩展） | — | 语音数据 | 20 字节 = [u16 组序号][u16 分片 0/1/2][16 字节] |
| `01` | Output | LED | Map 内声明，无独立 Report Reference | — |
| `FB` | Output | — | 语音启动/停止控制 | 单字节 `01`/`00` |
| `FA` | Output | — | 未知（未试写成功过业务值） | — |

语音流（与 Realtek SPEC `IFLYTEK_VOICE_FLOW` 图 28 一致）：

1. 订阅 FC/F8 等 CCCD；FD02 可选（396 组语音全部是在订阅 FD02 的状态下采集，但无任何应答交互）。
2. 语音键按下 → F8 通知 `82 03 01`。
3. 主机向 FB 写 `01` → 遥控器开始 FC 语音流（每 20 ms 一组、3 个通知，组内容 48 字节 = 40B ICO 帧 + 能量 + 序号 + 重复痕迹）。
4. 语音键松开 → F8 `82 03 00`，遥控器发完缓冲后停止。
5. 主机向 FB 写 `00`。

**整条链路没有任何鉴权步骤**：主机不需要向遥控器证明身份，遥控器也不等待主机确认；FD02 上仅观察到一条 10 字节主动通知 `10 01 4b 2a 03 02 04 00 02 03`（连接初期，含义未解）。

## 2. 厂商库盘点（xiri.zip 内 43 个 .so，无 Java 层）

Java 层在盒子系统 APK 内（`libjiagu.so` 加固），插件只带了 native 库。JNI 导出符号显示它聚合了多家遥控器方案的主机端解码：

| 库 | Java 类（JNI 前缀） | 方案 |
| --- | --- | --- |
| `libicocodec.so` | （ICOCodec） | 讯飞 ICO = G.722.1，已完整逆向 |
| `libremote-control-jni.so` | `com.listenai.bleremotectrl.control.RemoteControlJNI` | 聆思/ListenAI：ICO 解码 + 鉴权 |
| `libnative-lib.so` | `com.belon.decoder.*Decoder` | Belon：SBC 短包/长包解码 |
| `libaudio_util_lib.so` | `com.belon.audio/util` | Belon：音频加密/`vertify` |
| `libjinju.so` | `com.jinju.voice.{ble,dongle}.JniUtil` | Jinju：BLE/dongle ADPCM 解码 |
| `libhbgdecode.so` | `com.hbgic.hjq.hbgicdecode.HbgicNativeApi` | HBGIC：SBC 解码（`setMode`/`initAudioPrepared`/`sendVoiceData`） |
| `libxdriver_xiri_d.so`、`libiflyblesvc_xiri_d.so` | （守护进程） | USB dongle 路径：hidraw 监控、dongle verify（crc16+password）、按键事件 JSON |

**关键结论：盒子的 GATT 链路终结在 USB dongle 固件里**（Android 侧只见 `/sys/class/hidraw` 设备），所以这个 zip 里没有任何 GATT 层写命令——找不到 FD00 相关内容不是遗漏，是它本来就不在那里。想要 GATT 写命令，只能问 dongle 固件或盒子 APK 的 Java 层，或对遥控器做受控实验。

### 2.1 家族识别与分发逻辑不在这份 zip 里

"主机如何判断遥控器属于哪个家族、该调哪套解码/处理代码"——这个分发决策从这份 zip 里**看不出来**，依据：

- zip 只有 native 库，没有 dex/APK；分发决策属于 Java 层，而盒子系统 APK 用 `libjiagu.so` 加固，不在插件包内。
- 对全部 43 个 .so 扫描家族/UUID/设备类型相关字符串（`FD00`、`AB5E`、device type、厂商号等）：各解码库内**没有任何 BLE 识别逻辑**，它们只是"被选中的执行者"，不是"选择者"。
- zip 内仅有的三处"识别/校验"痕迹都在 dongle 路径，不是 BLE 家族分发：
  1. `libxdriver_xiri_d.so` 的 `isIflytekDev()`：按 hidraw 描述符认 USB dongle 是不是讯飞设备；
  2. `libsbc.so`（实为 `com.freqchip.audiolib`，FreqChip 方案）的 `apkSystemIDCrc`/`driverSystemIDCrc`：APK 与 dongle 固件的 systemID CRC 互校，防错配，仍是 USB 侧；
  3. ListenAI `authorize`：芯片 ID 密文验真，验过即"正品 ListenAI 遥控器"，兼有家族确认作用（见第 3 节）。

因此分发逻辑只可能在这两处：**盒子系统 APK 的 Java 层**（加固，需从实机 dump）或 **dongle 固件**。生态内已知的可用识别信号（若自行实现主机端可参考）：服务 UUID 组合（FD00 vs AB5E ATVV vs …0003FD RTK）、DIS 软件标识串（本机 `XFRSD0D_...`，XF 前缀疑似讯飞固件）、广播厂商自定义数据（海信专利 CN110035308A 提出的"配对阶段按广播信息选主机解码器"即此类机制）、家族特有握手（如 ListenAI 的 FD00 挑战包）。本机这些信号中，除服务列表和 DIS 外均未系统采集。

> 2026-09-16 后续：第三方 Java 端已找到并反编译，其家族识别就是蓝牙设备名 `CMCC_Voice_Remote`、单家族、无分发逻辑，见第 4 节。

### 2.2 `isIflytekDev` 的判断逻辑（libxdriver_xiri_d.so 反汇编）

dongle 路径识别"这是不是讯飞遥控器设备"，对 hidraw 设备路径（`/dev/hidrawX`）做**两层判断**，设备名不参与（名字检查在插件 Java 层）：

**第一层：HID 报表描述符静态指纹。** `open(O_RDWR|O_NONBLOCK)` 后依次 `HIDIOCGRRAWINFO`、`HIDIOCGRDESCSIZE`（描述符不足 30 字节 → 判负，日志 "size is small"）、`HIDIOCGRDESC`，然后在描述符字节里扫描 31 字节特征（要求锚点字节为 `0x15`，即 Usage Page/Logical Min 项）：

```text
15 00              Logical Minimum (0)
26 FF 00           Logical Maximum (255)
19 00              Usage Minimum (0)
29 1F              Usage Maximum (0x1F)
75 08              Report Size (8)
95 1F              Report Count (31)
91 00              Output (Data,Array,Abs)   ← 31 字节 vendor Output 报表
15 00 26 FF 00     （同上一段重复）
19 00 29 1F 75 08 95 1F
81 00 C0           Input (Data,Array,Abs) + End Collection
```

即报表描述符里必须存在一对 **31 字节 vendor Output + 31 字节 Input 报表**（"smart_ctrl" 通道）。不匹配 → "hid(%s) desc not same"。

**第二层：动态口令挑战。** 指纹命中后（"desc same, verify ->"）：

1. 生成 4 个随机数 `rnd[i] = rand() % 48`；
2. 写 32 字节命令 `{01 08 rnd[0..3] crc16(前6字节) 补零}`，非阻塞写，EAGAIN 时 epoll 等 50 ms；
3. 读 32 字节响应（"dongle feedback"），`crc16(响应前8字节) == 0` 否则 "verifyDongle, crc error"；
4. **口令核对**：要求 `响应[2..5] == "Trinity ISP 1.0 by Garfield 0804for Cicely  0423"[rnd[0..3]]`——密码表就是紧随特征串之后的这 48 字节 ASCII 字符串（"Trinity ISP 1.0"，作者署名 Garfield）。设备端固件必须内置同一字符串才能给出正确应答；
5. 外层 `iflytekVerify` 每 60 s 轮询 `/sys/class/hidraw`，每设备最多验证 3 次（"dongle verify 3 times"）。

**对本机的判定（已离线证实）**：遥控器直连盒子内置蓝牙时，内核 uhid 的描述符就来自其 HOGP Report Map。本机 Report Map 原始字节（169 字节，`data/raw/remote-session.jsonl` handle 0x2A 的 read）经特征扫描**不含该 31 字节指纹**——全 Map 只有键盘（ID 01）、Consumer（ID 03）、20 字节扩展 Input（ID 04/FC/F8）、1 字节 Input（ID F9），没有任何 vendor Output 项。即 `isIflytekDev` 必然返回"desc not same"：**这套第三方栈直连时认不出联通遥控器**。检查脚本见 [scripts/isiflytek_hid_check.py](../scripts/isiflytek_hid_check.py)。

真机复核步骤（任一即可）：

1. 复读 Report Map 对比：配对后读 HID service 的 Report Map 特征（0x2A4B），把 hex 交给
   `python scripts/isiflytek_hid_check.py --hex <hex>`；预期输出 NOT FOUND（与 data/raw 存档一致则说明固件未变）。
2. 在跑 svciflybl 的盒子上直连遥控器，`logcat`/串口过滤 `hid(`、`desc`、`verify`：预期出现
   `hid(hidrawX) desc not same`，且插件收不到任何按键事件。
3. 若手头有 CMCC dongle：把它插 PC/盒子，对 dongle 的 hidraw 节点跑
   `python scripts/isiflytek_hid_check.py --hidraw /dev/hidrawX`；预期 FOUND（指纹本来就是 dongle 自己的 USB 描述符），
   随后守护进程会发起 Trinity 挑战。此时再让 dongle 配对联通遥控器，即可验证 dongle↔遥控器空口是否互通——这是唯一可能让联通遥控器跑在该栈上的路径（需 dongle 侧接受新配对）。

若第 1 步在某台联通遥控器上输出 FOUND，则说明存在与 CMCC 平台同固件的联通批次，值得重新评估直连路径。

## 3. ListenAI 主机端协议（`libremote-control-jni.so` 反汇编）

JNI 接口五个：`createDecoder` / `decode` / `destroyDecoder` / `unpackChipId` / `authorize`。

解码与我们对 `libicocodec.so` 的结论完全一致：`decode` 收 40 字节帧，按 `ICODecoder(state, frame, 20 /*半字*/, pcm640, &outlen)` 调用，回填 `outlen*2` 字节 PCM。

鉴权相关两个函数的语义：

**`unpackChipId(packet40) → 8 字节`**

- `packet40` 由两个 20 字节子记录组成（rec0 = [0..19]，rec1 = [20..39]）；
- 约束：`rec0[2]==1 && rec1[2]==2`，或对称的 `rec0[2]==2 && rec1[2]==1`，否则返回 -4097；
- `chip_id0 = u32le@(rec0+3)`，`chip_id1 = u32le@(rec1+3)`，拼接输出。

**`authorize(packet40) → 0（通过）/ -4097（失败）`**

- 同样的 rec0/rec1 结构检查；
- 16 字节密文 = `rec0[0x0a..0x11] ‖ rec1[0x0a..0x11]`；
- 密钥：遍历库内全局表 `_key`（1024 字节，位于 .rodata 0x416a4），取 u16 表项对 13 取模、与循环下标 `i` 按位或得到源偏移（`i = 0x0,0x10,…,0x3f0` 共 64 轮），散乱重建 64×8 字节缓冲，取其前 16 字节作 AES-128 密钥；
- AES-128-ECB 解密那 16 字节，明文必须逐字节等于 `{chip_id0, chip_id1}`。

### 这就是"authorize 是干什么的"的答案

`authorize` 是**主机验证遥控器**的单向检查，不是协议握手：

- 方向：遥控器主动推送一个 40 字节"证书"（两段 20 字节通知，类型字节 1/2，内含芯片 ID 和密文），主机收到后本地核对。它防的是山寨遥控器冒充正品去用盒子的付费讯飞 ASR 服务——保护的是主机侧生态，不是遥控器拒绝未授权主机。
- 它不产生任何回复，不开启任何通道。语音链路的"门"在遥控器侧，钥匙就是已实测的三步：订阅 → F8 按键报告 → 写 FB `01`。
- 所以**没有 authorize 也能正常用遥控器**：设备端 SDK 只要不实现这个主机侧的验真（或验了也只记日志），一切功能照常。本仓库全部 396 组语音就是零鉴权采集的；Realtek 参考流程图里同样没有鉴权环节。
- 需要它的场景只有一个方向：**仿真遥控器去骗原装盒子**——那时必须生成合法的 40 字节挑战包，才需要 `_key` 表和上述算法。另外原装盒子 APK 的 Java 层可能在验真失败后拒绝解码音频（盒子策略），但那是盒子行为，不是 BLE 协议要求。

### 与本机的对应关系（待验证）

本机 FD00/FD02 上只见过 10 字节通知，从未捕获 40 字节挑战包。本机音频=ICO 与 ListenAI 方案吻合，但 FD00 语义是否就是上述鉴权通道、10 字节消息是什么，需要长时间抓包或受控实验确认。

## 4. 第三方 Java 主机端（CMCC_PLUS 仓库）

来源：[c07758942/CMCC_PLUS](https://github.com/c07758942/CMCC_PLUS) 内的 `cmcc语音遥控器助手_v1002.apk`（包名 `com.android.cmremote`），基于 [SHARJECK/VoicePlus](https://github.com/SHARJECK/VoicePlus) SDK（那只是 IPC 桥：解码后的 PCM 16 kHz/16-bit 经 `AudioTransfer` 发给夏杰语音 `com.peasun.aispeech`）。以下经 jadx 反编译核对。

**家族识别：只支持一种遥控器**——蓝牙设备名包含 `CMCC_Voice_Remote`（监听 HID profile 连接状态广播，连上时自动重连 socket）。整个 dex 没有任何其他家族的调用（freqchip/belon/jinju/hbgic/listenai 均无，字符串 grep 命中的是 belong 之类误匹配），也没有 authorize/chipId 调用。上一节的"多家族分发"在第三方实现里不存在——那仍是原厂盒子 Java 层的事。

**它不直接做 BLE**：全部业务代码没有任何 `BluetoothGatt` 调用，遥控器语音经 `svciflybl` 守护进程（即 xiri.zip 的 `libiflyblesvc`，读 hidraw）的 unix socket `/tmp/iflytek_ble_8431060cd56c47228782aa2e772a31b2` 获取。`onCreate` 无条件连 socket；名字检查只影响"遥控器连接事件触发重连"这一条路径。

### dongle socket 协议（本节新提取）

所有包共享 magic `F2 E0 D1 C5`：

| 方向 | 长度 | 布局（magic 后） | 含义 |
| --- | --- | --- | --- |
| daemon→app | 20 | [4..17] 未知，[18]=`03`，[19]=`01`/`00` | 语音键按下/松开事件 |
| app→daemon | 18 | u32 0 ‖ u32 6 ‖ u32 4 ‖ u16 1 | 语音开始（= 直连方案写 FB `01` 的等价物） |
| app→daemon | 18 | u32 0 ‖ u32 7 ‖ u32 4 ‖ u16 2 | 语音停止（= 写 FB `00`） |
| app→daemon | 18 | u32 0..3 ‖ u32 4 ‖ u16 {2,0x11,0x12,0x11} | socket 建立时连发 4 条订阅命令 |
| daemon→app | 62 | [22..61] = 40 字节 ICO 帧 | 语音数据；seq/frag 重组已由 dongle/daemon 完成 |

与直连 BLE 流程逐拍对上：按键事件 → 主机发开始命令 → ICO 流 → 松开事件 → 主机发停止命令。可见 dongle 方案里启停命令同样由宿主应用发出，dongle 固件只做转发与重组。

### 4.1 FD00/FD02 与 dongle 路径的关系（不是"报文格式被改"）

FD00/FD02 来自**遥控器固件自身**的 GATT（直连抓包即可见），不在任何主机侧代码里：`libiflyblesvc` 全库只有 `/sys/class/hidraw`、`/dev/%s`，零 Bluetooth/GATT/FD00 引用；插件同样没有。dongle 路径看不到 FD00 的原因是**观测面不同**，不是空口协议变更：

```text
空口（遥控器 ↔ 盒子）:  标准 BLE HID（F8/FC 报表、写 FB 启停，与直连抓包一致——待证）
内核:                  BLE HID → uhid → /dev/hidrawN；或 USB dongle → /dev/hidrawN
守护进程 svciflybl:    读 hidraw，重新封装为 F2E0D1C5 socket 帧
宿主 App:              socket → ICO 解码 → PCM → 夏杰语音
GATT 层（含 FD00）:    被 dongle 固件 / 系统 BT 栈消化，宿主永远不可见
```

即 hidraw/socket 上看到的格式差异（62 字节帧、20 字节事件、18 字节命令）是**接收侧本地封装**，不能当作 CMCC 改过空口报文的证据。

一个架构细节：插件同时监听 `USB_DEVICE_ATTACHED` 和 `android.bluetooth.input.profile.action.CONNECTION_STATE_CHANGED`、`ACL_CONNECTED`——CMCC 盒子两种接法都支持：外接 dongle，或遥控器**直连盒子内置蓝牙**（BLE HID 经内核同样落成 hidraw 节点）。`isIflytekDev` 逐个 hidraw 设备核对描述符，就是在两种来源里认遥控器。

FD00 的服务对象因此有两种假说：(a) 原厂**直连型**宿主（不走 dongle 的盒子 App）用它做初始化/鉴权——FD02 那条 10 字节消息属于此类未解项；(b) dongle 固件内部消费、无需转发。已实测语音完全不依赖 FD00 交互，它至少是可选的。

### 对本机（联通）的参照价值

- 同源印证：移动 CMCC 与联通遥控器同为 ICO 音频、同启停流程，dongle hidraw 报文格式（尤其 62 字节帧的 22 字节头）值得日后抓 USB 时核对。
- 名字门为 `CMCC_Voice_Remote`；本机 BLE 名称未记录。插件对联通遥控器未必自动触发，但 `onCreate` 无条件连 socket，直接跑也可能工作，待实测。
- 整个 dongle 栈（守护进程 + 宿主）没有 FD00/FD02 概念——FD00 的语义只存在于直连 BLE 方案（或被 dongle 固件内部消化），第三方宿主根本不接触。

## 5. 尚未解决的指令与验证途径

- FD02 是否接受主机写入（启动应答？查询？）：无源码依据，不做盲写，仅在受控实验里低风险探测；相关实验设计见[下一步实验](next-experiments.md)。
- 长连接抓包确认 FD02 是否周期性/事件性推送 40 字节鉴权挑战。
- FD00 服务下 FD01 特征是否存在（本次 discovery 只列出 FD02）。
- FA Output 的业务用途（keymap 阶段仅确认过 ATT 写成功回执）。
