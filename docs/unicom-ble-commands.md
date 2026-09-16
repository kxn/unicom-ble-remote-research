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

## 4. 尚未解决的指令与验证途径

- FD02 是否接受主机写入（启动应答？查询？）：无源码依据，不做盲写，仅在受控实验里低风险探测；相关实验设计见[下一步实验](next-experiments.md)。
- 长连接抓包确认 FD02 是否周期性/事件性推送 40 字节鉴权挑战。
- FD00 服务下 FD01 特征是否存在（本次 discovery 只列出 FD02）。
- FA Output 的业务用途（keymap 阶段仅确认过 ATT 写成功回执）。
