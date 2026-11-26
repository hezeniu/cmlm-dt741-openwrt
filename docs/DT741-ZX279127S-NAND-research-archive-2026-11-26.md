# ZTE DT741 / ZX279127S NAND 移植研究存档

**存档日期：2026-11-26**  
**用途：进入 Linux 6.18 Denali 驱动适配前的技术基线**  
**研究范围：仅记录 NAND 控制器及其必要 SoC 依赖。**

本文区分“已确认事实”“强推断”和“后续可验证事项”。不要把待验证项当成已确认参数。后续代码适配应以本文已确认内容为基线，避免重复反汇编和重复实测。

---

## 1. 目标硬件与研究范围

目标设备为 ZTE DT741，SoC 为 Sanechips / 中兴微电子 ZX279127S 系列。

已知硬件：
- ARM Cortex-A9，约 1GHz。
- DDR：512MiB。
- NAND：Toshiba 256MiB 并行 SLC。
- NAND page：2048 bytes。
- OOB：64 bytes。
- Erase block：128KiB。
- NAND ID：`0x1590DA98`；运行时 Manufacturer ID `0x98`、Device ID `0xDA`。
- 原厂 Linux：4.1.25+；原厂 U-Boot：2013.04-svn171642。

本次移植目标只包括：
- DDR / memory 描述；
- NAND 控制器及 NAND flash；
- NAND 所需的 clock、IRQ、DMA、SoC 控制寄存器等依赖。

GPON、Wi-Fi、PCIe WLAN 不属于当前目标。

## 2. 原厂 NAND 设备树与 MMIO 资源

原厂 DTS 节点：

```dts
nand@00d80000 {
    compatible = "denali,denali-nand-dt";
    reg = <0x00d80000 0x07c00000
           0x00d00000 0x00080000>;
    reg-names = "nand_data", "denali_reg";
    interrupts = <0 20 4>, <0 33 4>;
    clocks = <&topcrm 0x31>;
    dma-mask = <0xffffffff>;
    status = "okay";
};
```

资源对应：
- `nand_data`：base `0x00D80000`，size `0x07C00000`。
- `denali_reg`：base `0x00D00000`，size `0x00080000`。
- `nand_data` 是 Denali indexed host/data interface 窗口；`denali_reg` 是控制器寄存器窗口。
- 原厂有两个 IRQ：`<0 20 4>` 和 `<0 33 4>`。
- 原厂只声明一个 unnamed clock：`<&topcrm 0x31>`。
- DMA mask 为 32-bit：`0xffffffff`。
- 原厂节点没有 `clock-names`、`reset` / `reset-names`，也没有 NAND 子节点。

`/proc/iomem` 已确认两个窗口与以上地址范围一致。

### 中断号

运行时 NAND IRQ：
- Linux IRQ：19。
- GIC HW IRQ：65。
- GIC HW IRQ 65 对应 SPI 33，即原厂 DTS 第二个中断 `<0 33 4>`。

因此原厂实际使用的是第二个 IRQ。第一项 `<0 20 4>` 不应未经分析就当作 NAND IRQ。

## 3. NAND 芯片与几何参数

原厂运行时识别日志：

```text
ID of nandflash: 0x1590da98
denali special 0
nand: device found, Manufacturer ID: 0x98, Chip ID: 0xda
nand: Toshiba NAND 256MiB 3,3V 8-bit
nand: 256 MiB, SLC, erase size: 128 KiB, page size: 2048, OOB size: 64
8 bit device!
```

这与原厂 NAND 参数表 Toshiba record ID `0x1590DA98` 匹配。

型号字符串在原厂表中疑似少了一个字符（`TC58VG1S3ETA00`），可能对应 `TC58NVG1S3ETA00`。但移植无需依赖型号字符串：ID 和运行时几何参数已足以确定当前芯片配置。

注意不要与其他 Toshiba 型号混淆；本设备实际确认的是 256MiB、2KiB page、64B OOB、128KiB erase 的这颗芯片。

## 4. 原厂 MTD 分区

NAND 总容量：`0x10000000`（256MiB）。

按物理 offset 的原厂分区布局：

| 分区 | Offset | Size |
|---|---:|---:|
| u-boot | `0x00000000` | `0x00200000` |
| kernel0 | `0x00200000` | `0x02000000` |
| kernel1 | `0x02200000` | `0x02000000` |
| others | `0x04200000` | `0x00600000` |
| parameter | `0x04800000` | `0x00400000` |
| usercfg | `0x04C00000` | `0x00800000` |
| middleware | `0x05400000` | `0x00400000` |
| wlan | `0x05800000` | `0x00400000` |
| phoneapp | `0x05C00000` | `0x00200000` |
| phoneapp1 | `0x05E00000` | `0x00200000` |
| osgi | `0x06000000` | `0x01E00000` |
| osgi1 | `0x07E00000` | `0x01E00000` |
| plugin_data | `0x09C00000` | `0x06400000` |

原厂 `/proc/mtd` 的 MTD 编号顺序并不等于 offset 顺序，不能按 mtd 编号推断物理顺序。

A/B：
- A：kernel0（mtd3）+ osgi（mtd10）。
- B：kernel1（mtd6）+ osgi1（mtd12）。
- 原厂当前启动 A。
- 第一轮测试规划应保留 A，优先考虑 B 槽；任何实际写 Flash 操作都必须另行明确授权。

## 5. 原厂驱动来源与 Denali 控制器能力

原厂并非直接使用 Linux 4.1 通用 Denali 驱动，而是中兴自研驱动：

`drivers/mtd/nand/zte/zx_denali_nand.c`

从原厂 kernel strings 已确认相关符号/字符串，包括：
- `denali,denali-nand-dt`
- `denali_erase`
- `denali_exist`
- `zx_denali_nand.onfi_timing_mode`
- `denali_reg`
- `nand_data`
- `ecc err on read_page`
- `correct %d bit errors on page %x`
- `reset bank failed`

驱动包含 NAND 初始化、识别、DMA、ECC、OOB、page read/write、erase、bank reset、中断等功能。没有完整原厂 C 源码，关键行为通过 ARM 汇编反推。

### 运行时寄存器读数

在 `denali_reg` 窗口读取：

| 寄存器 | 地址 | 实测值 | 含义 |
|---|---:|---:|---|
| REVISION | `0x00D00370` | `0x00000005` | Denali revision 5.0（上游读取后 `swab16`） |
| FEATURES | `0x00D003F0` | `0x000008D1` | 控制器 feature bits |
| SPARE_AREA_SKIP_BYTES | `0x00D00230` | `0x00000002` | 跳过 OOB 前 2 字节 |
| MANUFACTURER_ID | `0x00D00300` | `0x00000098` | Toshiba |
| DEVICE_ID | `0x00D00310` | `0x000000DA` | Toshiba |

`FEATURES=0x8D1` 的解读：
- N_BANKS 字段旧编码对应最大 4 banks；
- ECC_MAX_ERR 字段值 4；
- DMA 支持；
- CMD_DMA 支持；
- INDEX_ADDR 支持；
- PARTITION、XDMA_SIDEBAND、GPREG 等对应位未置位。

**最大 bank 能力为 4，不等于实际连接了 4 颗 NAND。**

运行时另有：
- `RB_PIN_ENABLED (0x60)` = 1。
- `DEVICES_CONNECTED (0x250)` = 1。

这与原厂单颗 NAND / Bank 0 的实际配置相符。移植时保留控制器最大 bank 能力，不要把最大 banks 数错误改成 1；实际只描述一个 NAND target。

原厂日志 `denali special 0`，表示未启用原厂针对特殊 NAND ID 的 special command 路径。

## 6. ECC、step size 与 OOB：已实测确认

对 `/dev/mtd3` 做只读 `nanddump`：

```sh
/sbin/nanddump --bb=dumpbad -o -p -s 0 -l 4096 /dev/mtd3
```

结果：
- ECC failed：0。
- ECC corrected：0。
- bad blocks：0。
- block size：131072。
- page size：2048。
- OOB size：64。

前两页 OOB 实际布局：
- OOB `[0..1]`：`FF FF`，BBM / bad-block marker 区域。
- OOB `[2..33]`：32 bytes ECC parity。
- OOB `[34..63]`：30 bytes free。

原厂初始化明确设置：
- `SPARE_AREA_SKIP_BYTES = 2`。
- `ECC_ENABLE = 1`。
- `ECC_CORRECTION = 4`。

Denali ECC bytes 计算公式与实测匹配：
- step 512 bytes、strength 4；
- 每个 512-byte step 需要 8 bytes ECC；
- 2048-byte page 有 4 个 step；
- 总 ECC parity = 32 bytes。

如果 step 为 1024，则只会产生 16 bytes ECC，与实测不符。

**移植参数已确定：**

```c
.ecc_strength = 4,
.ecc_step_size = 512,
.oob_skip_bytes = 2,
```

OOB 结构：
- 2 bytes BBM/skip；
- 32 bytes ECC；
- 30 bytes free。

这是本次最重要的 NAND 参数之一，不需要再重复猜测或用 `CFG_DATA_BLOCK_SIZE` 推断。

## 7. 原厂 ECC 行为与上游 Denali 新旧模式差异

### 原厂初始化设置

通过原厂汇编确认以下写入：

| 寄存器 | Offset | 原厂写入 |
|---|---:|---:|
| RB_PIN_ENABLED | `0x060` | 1 |
| CHIP_ENABLE_DONT_CARE | `0x0D0` | 0 |
| ECC_ENABLE | `0x0E0` | 1 |
| GLOBAL_INT_ENABLE | `0x0F0` | 先 0，配置后 1 |
| SPARE_AREA_SKIP_BYTES | `0x230` | 2 |
| DEVICES_CONNECTED | `0x250` | 1 |
| DMA_ENABLE | `0x700` | 初始化时 0，传输时开关 |
| ECC_CORRECTION | `0x1B0` | 4 |

原厂读页还会：
- 设置 `TRANSFER_SPARE_REG (0x10)` 为 0；
- DMA 传输主数据区；
- 通过 `ECC_COR_INFO (0x650)` 读取纠错统计。

### 关键：原厂使用 bit 1，不使用 bit 0

原厂初始化时对四个 bank 的 `INTR_EN` 都写入 `0x21FE`：

| Bank | INTR_STATUS | INTR_EN |
|---|---:|---:|
| 0 | `0x410` | `0x420` |
| 1 | `0x460` | `0x470` |
| 2 | `0x4B0` | `0x4C0` |
| 3 | `0x500` | `0x510` |

`0x21FE` 包含 bit 1、2、3 等事件，但排除了 bit 0。

原厂 IRQ handler `0xC027E050`：
1. 根据 bank 选择对应的中断状态寄存器；
2. 读取状态并与使能掩码相与；
3. W1C 清除有效状态；
4. OR 到软件累计状态 `[denali + 0x57c]`；
5. 唤醒等待队列。

原厂等待 helper `0xC027DA08`：
- 接收事件 mask；
- 检查累计状态；
- mask 中任意一位出现就返回；
- 返回累计状态值，并清除本次匹配的 mask 位；
- 等待超时则返回 0。

### 原厂读页路径

读页函数入口：`0xC027E4C8`。

已确认关键流程：
1. `ECC_ENABLE = 1`。
2. `TRANSFER_SPARE_REG = 0`。
3. 配置 DMA 读取主数据。
4. 调用等待 helper，mask = `0x0E`。
5. mask 任意一位出现即返回；包括：
   - bit 1：ECC_ERR（旧 Denali 定义）；
   - bit 2：DMA_CMD_COMP；
   - bit 3：TIME_OUT。
6. 检查返回状态 bit 1。
7. bit 1 置位：调用 `0xC027E418` 检查数据缓冲区是否全 `FF`。
8. bit 1 未置位：读取 `ECC_COR_INFO (0x650)`，取低 7 bits 作为纠错位数。
9. 关闭 DMA、完成 DMA buffer 同步/解除映射等清理。
10. 原厂函数最终返回 0。

`0xC027E418` 只扫描传入的数据区是否全 `FF`；它不读取 OOB，也不读取 ECC error address。调用者没有使用其返回值。因此原厂这段 erased-page 检查的结果没有明显参与最终错误返回，不能把它当成完整、正确的 MTD erased-page recovery 实现。

### 原厂写页路径

写页路径使用等待 mask `0x14`：
- bit 2：DMA_CMD_COMP；
- bit 4：PROGRAM_FAIL。

写页路径同样启用 ECC、配置 DMA，并在完成后关闭 DMA。此等待逻辑与上游 DMA 写入流程比较接近。

### 与上游 Linux Denali 的差异

上游 Denali 代码有两种主要 ECC 路径：

**旧软件纠错路径**
- 使用 `ECC_ERR`（bit 1）；
- 读取 `ECC_ERROR_ADDRESS (0x630)` 和 `ERR_CORRECTION_INFO (0x640)`；
- 软件对 DMA 读出的数据执行 bit correction。

**新硬件自动纠错路径（`DENALI_CAP_HW_ECC_FIXUP`）**
- 控制器硬件自动纠错；
- 使用 `ECC_UNCOR_ERR`（bit 0）作为不可纠正错误中断；
- `ECC_COR_INFO` bit 7 表示不可纠正错误；
- `ECC_COR_INFO[6:0]` 表示纠正位数；
- 不使用旧式 `0x630/0x640` 软件修正流程。

原厂驱动：
- 不读取 `0x630/0x640`；
- 使用 `ECC_COR_INFO[6:0]`；
- 但中断配置启用 bit 1、排除 bit 0；
- 原厂读页 bit 1 分支执行数据区全 `FF` 检查；
- 原厂没有检查 `ECC_COR_INFO` bit 7。

因此原厂表现为**硬件 ECC 纠错数据路径 + ZX279127S 特有的 bit 1 中断语义**。不能直接套用上游 `DENALI_CAP_HW_ECC_FIXUP` 的完整中断语义，也不能退回旧软件逐字节纠错路径。

### 当前建议的适配方式

基于 Linux 6.18 上游 Denali 驱动增加独立 ZX279127S quirk / 专用 ECC 中断处理：
- 保留上游 DMA32 和通用 NAND 框架；
- 使用原厂 bit 1 / bit 2 / bit 3 等中断配置；
- 正常纠错计数读取 `ECC_COR_INFO[6:0]`；
- ECC 异常路径按 Linux MTD 语义正确处理不可纠正错误和 erased page；
- 不调用旧式软件逐字节 correction；
- 不直接照搬上游 HW fixup 模式的 bit 0 中断判断。

不要把原厂错误处理中的“调用全 FF 检查但丢弃结果”原样复制为新驱动设计。

## 8. DMA：可沿用上游实现的部分

原厂有 32-bit DMA mask：`0xffffffff`。

原厂 DMA 配置函数 `0xC027DD38` 通过 indexed interface 写入 DMA 参数，包含：
- DMA 命令/页地址；
- DMA 地址高 16 bits；
- DMA 地址低 16 bits；
- 中断/burst 配置。

命令寄存器相关地址包括 `0x2001` / `0x2101`，DMA 地址高低寄存器索引 `0x2200` / `0x2300`，配置寄存器索引 `0x2400`。

该序列与上游 Denali 32-bit DMA 配置流程相符。建议沿用 Linux 6.18 上游 DMA32 实现，不重新实现 DMA 地址拆分和命令寄存器操作。

原厂 `FEATURES` 显示 DMA 和 CMD_DMA capability，但不能仅凭 CMD_DMA feature bit 就认定原厂实际使用了 command DMA；当前已确认的 page read/write 路径是普通 DMA 数据传输。

## 9. Clock：已确认的时钟树

原厂 NAND clock phandle `<&topcrm 0x31>` 对应 `lb_nandflash_wclk`。

相关时钟：
- `lb_nandflash_wclk`：NAND 控制器工作时钟，约 25MHz。
- `lb_nandflash_100m_wclk`：100MHz，作为工作时钟的父级。
- `lb_nandflash_ahb_hclk`：独立 AHB 总线时钟，供控制器总线访问相关。

时钟关系：
- `nand_wclk_sel` mux 位于 `0x9400000C` bit 4；
- 用户实测 `0x9400000C = 0x1373`，bit 4 = 1，选择 100MHz 时钟源；
- `lb_nandflash_100m_wclk` 为 100MHz；
- `lb_nandflash_wclk` 经固定除频 /4，得到 25MHz；
- 100MHz / 25MHz = 4，符合上游 Denali 对 `clk_x` 与 `clk` 比值的要求范围。

时钟 gate：
- gate 寄存器 `0x94000014`；
- bit 15：100MHz NAND clock；
- bit 14：AHB clock；
- 用户实测寄存器值为 0；
- 这两个 gate 使用 `CLK_GATE_SET_TO_DISABLE` 反向极性，0 表示 enabled，1 表示 disabled。

原厂驱动只显式获取/启用一个 unnamed clock，即 `lb_nandflash_wclk`。AHB clock 在原厂 DTS 中没有作为第二个 clock 声明，但硬件时钟树存在且运行时 gate 状态为 enabled。

移植建议：
- 正确声明/启用 NAND core clock（25MHz）及其 100MHz 父时钟；
- AHB clock 作为必要总线依赖保留在 SoC clock/设备树设计中；
- 不要声称已经通过关闭 AHB gate 的实验验证它是否绝对必需；
- ECC 没有独立 clock 的证据。

## 10. SoC 版本、IRQ 选择与 pinmux / 控制寄存器

原厂 SoC 版本判断函数 `0xC0019258` 会读取物理地址 `0xF4040000`，并与以下 ID 比较：

| Chip ID | internal version | IRQ index |
|---|---:|---:|
| `0x27912700` | 1 | 0 |
| `0x27912800` | 2 | 0 |
| `0x27912810` | 3 | 0 |
| `0x27912710` | 4 | 1 |

用户尝试 `devmem 0xF4040000 32` 得到 Bus error，未能直接读取芯片 ID。不要盲目重复该读取。

实际 IRQ 为 GIC SPI 33，对应原厂第二个 IRQ，因而强烈指向 internal version 4；但这只是基于 IRQ 选择的推断，不是直接读出的 silicon ID。

原厂 NAND init 会对 SoC 控制寄存器做 read-modify-write：
- `0xF0600004`
- `0xF0600008`

version 4 路径：
- 对 `0xF0600004` 清 bits 14–29；
- 对 `0xF0600008` 清 bits 0–11。

version 1–3 路径：
- 对 `0xF0600008` 清 bits 0–27。

这些寄存器字段尚未映射到可靠的 NAND pin 名称。移植时只能依据原厂掩码保留相应的 RMW 行为，不能擅自命名为 NAND_DATA/CLE/ALE，也不能整寄存器覆盖。

原厂 DTS 和目前检查过的初始化路径没有发现明确的 SoC reset 控制操作。Denali 内部 bank reset 与 SoC reset 是两回事，不要凭上游通用驱动存在 reset control 就给 DT741 虚构 reset phandle。

## 11. 后续可以再查、当前不阻塞代码适配的事项

以下问题已明确记录，但可以放到代码适配后或有实际设备测试条件时再查：

1. **bit 1 与 `ECC_COR_INFO` bit 7 的真实关系**
   - 原厂中断使能/IRQ/读页逻辑明确使用 bit 1；
   - 原厂没有检查 ECC_COR_INFO bit 7；
   - 尚未在真实不可纠正 ECC 错误下观察两个标志是否同时置位。
   - 可在安全的测试环境中通过可控 ECC 错误或损坏测试页验证；不要为了测试破坏 A 槽或重要数据。

2. **读页 bit 1 是否可能早于 DMA_CMD_COMP**
   - 原厂等待 mask `0x0E` 是 any-bit completion；
   - 静态逻辑表明 bit 1 可以单独令等待返回；
   - 尚未通过硬件事件时序确认它是否会在 DMA 数据完全落入内存前出现。
   - 新驱动应避免在没有 DMA 完成保证时过早读取 DMA buffer；需结合上游 DMA 同步和设备实测谨慎实现。

3. **ECC 异常分支的真实语义**
   - 原厂将 bit 1 作为特殊 ECC 分支；
   - 该分支调用全 `FF` 检查但丢弃返回值；
   - 不能仅凭静态代码断言 bit 1 在此芯片上严格等价于 uncorrectable ECC。
   - 适配时按 Linux MTD 正确语义实现，并保留日志/调试能力。

4. **SoC internal version 的直接确认**
   - 当前根据 IRQ index 强烈推断 version 4；
   - 直接访问 `0xF4040000` 曾 Bus error；
   - 后续可从其他安全可访问的 SoC ID/boot log 来源确认，不要重复盲读该地址。

5. **AHB gate 的必要性**
   - clock tree 中存在独立 AHB clock，原厂运行时 gate enabled；
   - 原厂 DTS 只显式取得一个 unnamed clock；
   - 尚未做关闭 AHB gate 的实验。移植时先保留 AHB 依赖，不需要为确认它而冒险关闭。

6. **Toshiba 参数表中少量字段**
   - 已确认并且移植必需的 timing 字段已记录在项目研究记录中；
   - 个别未找到用途的 record byte 不应擅自解释成某个 Denali timing；
   - 不影响当前 ECC、几何参数和 DMA 适配。

7. **原厂 erased-page 检查是否存在未恢复的调用副作用**
   - 当前看到 `0xC027E418` 的返回值没有被调用者使用；
   - 可以在完整读页函数调用约定和编译器寄存器状态复核时再检查；
   - 不影响已经确认的 OOB/ECC step 参数。

## 12. Linux 6.18 适配时的实施基线

优先以 Linux 6.18 上游 `drivers/mtd/nand/raw/denali.c`、`denali.h`、`denali_dt.c` 为基础，使用平台 quirk 适配 ZX279127S。

已确认可直接作为实现基线的参数：

```c
/* 具体结构成员名以当前选用的 Linux 6.18 源码为准 */
ecc_strength = 4;
ecc_step_size = 512;
oob_skip_bytes = 2;
dma_mask = 0xffffffff;
```

设备描述必须体现：
- `nand_data` 和 `denali_reg` 两个 MMIO resource，顺序与 `reg-names` 对应；
- 使用原厂实际工作的第二个 IRQ（SPI 33）；
- NAND core clock 25MHz，以及 100MHz 父级时钟关系；
- AHB clock 依赖；
- 单颗 NAND target / Bank 0；
- Toshiba 256MiB、2KiB page、64B OOB、128KiB erase；
- 32-bit DMA。

ZX279127S quirk 需要负责：
- 原厂 `INTR_EN=0x21FE` 的事件掩码/初始化兼容；
- 原厂 bit 1 ECC 状态处理；
- `ECC_COR_INFO[6:0]` 纠错计数；
- 读页异常分支与上游 MTD 错误处理之间的正确衔接；
- 避免上游默认 HW ECC fixup bit 0 语义与原厂硬件中断配置冲突。

不要：
- 把最大 4 banks 误设为只支持 1 bank；
- 因原厂只连一颗 NAND 而改变控制器最大 banks 能力；
- 使用旧软件 ECC correction 寄存器路径；
- 未经证据添加 SoC reset；
- 擅自给 `0xF0600004/08` 位域起 pin 名；
- 把原厂错误的 erased-page 分支原样复制；
- 重新做已经完成的 ECC step/OOB 推断；
- 执行任何 NAND 写入或分区擦除操作，除非用户明确授权。

---

## 13. 关键结论速查

| 项目 | 结论 |
|---|---|
| 控制器 | Denali IP，原厂为 ZTE 自研驱动 |
| Denali revision | 5.0 |
| NAND ID | `0x1590DA98` |
| NAND 容量 | 256MiB |
| Page / OOB | 2048 / 64 bytes |
| Erase block | 128KiB |
| ECC strength | 4 |
| ECC step | 512 bytes |
| ECC parity | 32 bytes/page |
| OOB skip | 2 bytes |
| OOB free | 30 bytes |
| 实际 NAND target | 1，Bank 0 |
| 控制器最大 bank capability | 4 |
| DMA | 32-bit DMA |
| IRQ | 原厂第二个 IRQ，GIC SPI 33 |
| NAND core clock | 25MHz |
| NAND 100MHz parent | 100MHz，/4 到 25MHz |
| AHB clock | 独立存在，移植时保留 |
| 中断使能 | 四个 bank 的 `INTR_EN=0x21FE` |
| 原厂读等待 mask | `0x0E` |
| 原厂写等待 mask | `0x14` |
| 原厂纠错计数 | `ECC_COR_INFO[6:0]` |
| 原厂 bit 0 | 不使能 |
| 原厂 bit 1 | ECC_ERR 特殊分支 |
| 旧式 SW ECC correction | 原厂路径未使用 |
| 上游直接 HW ECC capability | 不能未经适配直接套用 |
| SoC version | 依据 IRQ 强烈推断 v4，尚非直接确认 |
| SoC reset | 目前无原厂证据 |
| 代码适配方向 | Linux 6.18 Denali + ZX279127S 专用 quirk |

**最终状态：NAND 基础硬件参数、ECC 几何、OOB、DMA、clock、IRQ 和原厂中断配置均已达到可开始代码适配的程度。未确认事项已列入后续验证清单，不阻塞第一版实现。**
