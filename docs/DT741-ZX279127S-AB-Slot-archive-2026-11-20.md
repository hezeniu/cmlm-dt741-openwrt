
DT741 光猫 U-Boot A/B 双槽启动(终结)

机制验证总结与切换操作规程

依据：u-boot.bin 全量反汇编 + 串口启动日志 + 运行时分区表　三重交叉验证

整理日期：2026 年 11 月 24 日

作者:

无极限/千总

目录

一、文档定位与结论摘要

1.1 一句话结论

1.2 当前活动槽

1.3 与切换直接相关的六个已验证事实

二、分区与物理地址事实

三、镜像头结构与字段语义

3.1 两处 CRC 的精确定义

3.2 magic 不参与 CRC 的原因

3.3 为什么 A/B 状态字段可以随意改

四、候选镜像的搜索与标志位

五、A/B 选择算法全过程

5.1 第一段：按标志位初选

5.2 第二段：BootImageNum 覆盖初选（决定性）

5.3 第三段：加载与二次校验

5.4 与本设备无关但值得记录的旁证

六、BootImageNum 读取器的完整行为

七、当前活动槽的判定链

八、切换操作步骤（方案甲，推荐）

8.1 第一步：零成本确认无人回写

8.2 第二步：整块读出并备份

8.3 第三步：定位目标字节并修改

8.4 第四步：擦除并整块回写

8.5 第五步：验证生效

九、切换操作步骤（方案乙，备用）

十、回滚方法

十一、禁止事项与风险

十二、OpenWrt 打包脚本改造清单

十三、命令速查（可直接复制）

十四、本次未验证或仍有不确定性的项目

一、文档定位与结论摘要

  本文只收录本次通过反汇编与启动日志双重验证过的事实，未验证的推测单独列在第十四节，不与结论混写。

验证手段共三类：

一是 u-boot.bin 全量反汇编（arm-none-eabi-objdump -D，正确基址 0x47EE0000）；

二是设备串口启动日志（含 addr / select / search / entry / mtdpart 各行）；

三是 运营商官方系统 运行时 /proc/mtd 与内核 cmdline。

  

1.1 一句话结论

  

A/B 槽(双系统切换)切换的软件开关在 others 分区的 BootImageNum 文本字段，它被 U-Boot 解析后直接作为候选槽下标；该字段是纯输入，U-Boot 不写回。第二个前置条件是目标镜像头 0x124 (binHead)必须为 00000000，本机两个槽该字段均为 0，因此只改 BootImageNum 一个字符即可完成切换。

  

1.2 当前活动槽

  

当前启动的是 kernel0，即 mtd3，物理起始 0x00200000。此前“当前跑 kernel1”的判断不成立，根因是把 0x00000000(0x128的值) 误认为活动槽标记，而事实相反：FFFFFFFF 才是活动槽。

  

1.3 与切换直接相关的六个已验证事实

  

事实一：U-Boot 不读分区表，它从物理 0x00100000 起、以 0x20000 为步长线性扫描 flash，靠镜像头 magic 识别候选。

事实二：候选按物理地址升序存入 result 数组，因此 result[0] 是 kernel0、result[1] 是 kernel1。

事实三：镜像头 0x128 与 0x124 共同决定候选标志位，且两者都位于 Header CRC 覆盖区间之外，改它们不需要重算任何 CRC。

事实四：others 中的 BootImageNum 解析值（只接受 0 和 1）在算法第二段直接成为最终槽号，优先级高于 0x128。

事实五：BootImageNum 读取器全程只读，唯一的写路径不存在，因此手改该值不会被 U-Boot 覆盖。

事实六：downver 命令的 kernel / rootfs / osgi / phapp 子命令在二进制里没有对应实现，属于空操作，不能作为切换入口。

二、分区与物理地址事实

以下偏移取自设备启动日志中 Linux 打印的 mtd 分区表，这是本主题唯一权威地址来源。此前按 /proc/mtd 列出顺序累加推算得到的 0x600000 与 0x3200000 是错误值，已废弃。

|   |   |   |   |   |
|---|---|---|---|---|
|设备|分区名|物理起始|长度|与 A/B 切换的关系|
|mtd0|whole flash|0x00000000|0x10000000|裸 NAND 读写时使用|
|mtd1|u-boot|0x00000000|0x00200000|引导程序，本次不动|
|mtd3|kernel0|0x00200000|0x02000000|候选 result[0]，当前活动槽|
|mtd6|kernel1|0x02200000|0x02000000|候选 result[1]，目标槽|
|mtd7|others|0x04200000|0x00600000|BootImageNum 文本所在分区|

补充两条与地址有关的验证结果：others 分区尾部紧接 0x04800000，而 sky_bakeup_info 搬移 tag 与 wlan 的源区起点正是 0x04800000，边界严丝合缝不重叠，所以该命令不会破坏 BootImageNum。设备擦除粒度为 0x20000（128KB），裸 NAND 写必须以整块为单位读改写。

  

三、镜像头结构与字段语义

kernel 分区内每个镜像的布局是：厂商 binheader 共 0x1E0（480）字节，紧接标准 Legacy uImage（含 64 字节 uImage 头），再往后是内核数据与 FF 填充。0x1E0 之后就是标准 uImage，这一点由加载校验指令硬编码地址 0x440001E0 直接证实，不是推测。

|   |   |   |   |
|---|---|---|---|
|偏移|长度|含义|验证依据|
|0x00|16|magic 识别区|四字依次比对 FFFFFFFF、44444444、55555555、AAAAAAAA|
|0x54|4|align16(0x1E0+长度)|U-Boot 不读此字段，仅打包工具记录用(异议)|
|0x58|4|uImage 总长（64 字节头+载荷）|被直接用作 Kernel CRC 的长度参数|
|0x5C|4|固定 0x1E0|binheader 自身长度|
|0x60|4|Kernel CRC32|与 CRC 计算结果比对的期望值(参与uboot校验)|
|0x68|4|同 0x54|U-Boot 不读此字段|
|0x110|4|Header CRC32|加载基址 +0x14 再偏移 0xFC 取得(参与uboot校验)|
|0x124|4|直选闸门|0 表示本槽允许被 BootImageNum 直指|
|0x128|4|优先标记|FFFFFFFF 表示本槽为活动槽(优先/默认槽)|
|0x12C|4|附加位|只影响记录位 bit4，不参与选择判据|

3.1 两处 CRC 的精确定义

  

Header CRC 存放在 0x110，计算区间为 0x14 到 0x110（不含端点），长度 0xFC，CRC 字段自身不参与。

Kernel CRC 存放在 0x60，起点 0x1E0，长度取 0x58 字段的值。两者都是标准 zlib CRC32。

  

计算顺序必须先是 Kernel CRC、后是 Header CRC，不能颠倒，因为 0x60 落在 Header CRC 的覆盖区间之内。

  

3.2 magic 不参与 CRC 的原因

  

代码里 magic 四字比对发生在 CRC 校验之前，且 CRC 起点被写死在基址加 0x14。原因是引导程序必须先信任识别字段才能知道头部布局与 CRC 字段位置，若 magic 自身被 CRC 覆盖就会形成循环依赖。这与常见引导程序设计一致，此处已由指令直接证实。

  

3.3 为什么 A/B 状态字段可以随意改

  

0x124、0x128、0x12C 都在 0x110 之后，落在 Header CRC 覆盖区间之外，也不在 Kernel CRC 范围内（Kernel CRC 只覆盖 0x1E0 起的数据）。这正是厂商的设计意图：允许只改状态字而不重算任何校验值。切换操作可以只动标志位而镜像保持二进制不变，其原理就在这里。

  

四、候选镜像的搜索与标志位

  

搜索函数入口 0x47EE0000 + 0x25888。它从物理 0x00100000 起、以 0x20000 为步长向上扫描，对每个窗口(牛加: mtd)先比 magic 四字，再做 Header CRC 校验，两项都通过才写入 result 数组并累加计数。日志中的 search=0x2 就是这个计数值，说明本机两个槽的镜像都完整合法，第二个槽不是空槽。

result 数组条目为 12 字节：偏移 0 是序号，偏移 4 是标志位（16 位读取），偏移 8 是 entry 地址，偏移 0xC 是镜像长度。

标志位由三条指令构造，还原后如下：

|   |
|---|
|ldr  r1, [镜像基址+0x128]        ; 读优先标记<br><br>cmn  r1, #1                      ; 是否等于 0xFFFFFFFF<br><br>movne r1, #0x80                  ; 否 -> bit0 = 0<br><br>moveq r1, #0x81                  ; 是 -> bit0 = 1<br><br>ldr  r0, [镜像基址+0x12C]        ; 读附加位<br><br>cmn  r0, #1<br><br>orrne r1, r1, #0x10              ; 非全 FF -> bit4 = 1（不参与判据）<br><br>ldr  r0, [镜像基址+0x124]        ; 读直选闸门<br><br>cmp  r0, #0<br><br>orreq r1, r1, #2                 ; 等于 0 -> bit1 = 1|

  

ldr  r1, [镜像基址+0x128]        ; 读优先标记

cmn  r1, #1                      ; 是否等于 0xFFFFFFFF

movne r1, #0x80                  ; 否 -> bit0 = 0

moveq r1, #0x81                  ; 是 -> bit0 = 1

ldr  r0, [镜像基址+0x12C]        ; 读附加位

cmn  r0, #1

orrne r1, r1, #0x10              ; 非全 FF -> bit4 = 1（不参与判据）

ldr  r0, [镜像基址+0x124]        ; 读直选闸门

cmp  r0, #0

orreq r1, r1, #2                 ; 等于 0 -> bit1 = 1 

  

bit7 由“通过校验”这一动作置位，两个候选都带；真正参与选择判据的是 bit0 与 bit1。判据常量是 0x82，即同时要求 bit7 与 bit1。

本机两槽实测值：kernel0 的标志为 0x83（0x128=FFFFFFFF，0x124=0），kernel1 的标志为 0x82（0x128=00000000，0x124=0）。该值的独立证据来自内核 cmdline 尾部打印的 0x83 0x82，与上述推导逐位吻合。

  

五、A/B 选择算法全过程

  

选择函数入口 0x47EE0000 + 0x265e0。它分三段执行，日志中 select 会打印两次，正是前两段各打印一次。

5.1 第一段：按标志位初选

|   |
|---|
|count == 1  : result[0] 满足 (flag & 0x82)==0x82 则选 0，否则看 result[1]<br><br>count == 2  : result[0].flag 满足 0x82 且 bit0 置位 -> 选 0<br><br>              否则 result[1] 满足 0x82 -> 选 (result[1].flag & 1)<br><br>              都不满足 -> 选 0<br><br>其它        : 返回 -1<br><br>随后打印 select=0x%x 与 search=0x%x|

本机 kernel0 标志 0x83 带 bit0，因此初选结果为 0。

5.2 第二段：BootImageNum 覆盖初选（决定性）

|   |
|---|
|bl  读取器(+0x25b44)              ; 从 others 解析 BootImageNum<br><br>if (返回值 >= 0 且 count > 1):<br><br>    r2 = result[返回值].flag<br><br>    tst r2, #2                    ; 该槽 bit1（即 0x124 是否为 0）<br><br>    movne r4, 返回值              ; 闸门开着 -> select = BootImageNum<br><br>    bne   完成<br><br>    r4 = !返回值                  ; 闸门关着 -> 换成另一个槽<br><br>    if (result[!返回值].flag & 2)==0:  r4 = 返回值<br><br>完成:<br><br>再次打印 select=0x%x 与 search=0x%x|

结论是 BootImageNum 覆盖 0x128。只要 others 里能解析出 0 或 1，且目标槽 0x124 为 0，最终槽号就等于 BootImageNum，与 0x128 是什么值无关。这也解释了此前“把目标镜像 0x128 改成 FFFFFFFF 却切不过去”的现象：那一项只影响第一段初选，会被第二段覆盖。

  

5.3 第三段：加载与二次校验

|   |
|---|
|entry = result[select].entry   ; 打印 entry 地址<br><br>读 flash -> 固定加载地址 0x44000000      ; 跨分区边界时走分段读<br><br>比对 magic 四字                          ; 失败打印 magic not found<br><br>Kernel CRC: 起点 0x440001E0<br><br>            长度 = [0x44000058]<br><br>            期望 = [0x44000060]          ; 失败打印 header crc error<br><br>通过则把该候选的 flag 低位置 1 或 8|

失败时还有一次回退：select 大于 0 时改试 0，否则改试 1，重跑一轮。

  

5.4 与本设备无关但值得记录的旁证

  

启动日志中 sky did not get cmd SKYWORTH_MAGIC_BACKUP, use normal flash table 说明 0x0E00 0000 的 34 字节备份区为空，走的是常规分区表，与 A/B 选择无关。mtddebug 命令实现位于 +0x2c384，确实按 read、write、erase 分发，但其 write 分支不接受分区名 others，因此改 others 只能走裸 NAND。(文末有help mtddebug佐证)

  

六、BootImageNum 读取器的完整行为

  

函数入口 0x47EE0000 + 0x25b44，共 124 条指令，有 8 个调用点，其中一处位于选择函数内，证明二者同属一条调用链。

|   |
|---|
|sub  sp, #0x1024                       ; 开 4KB 栈缓冲<br><br>bl   +0x18240 (r0=4)                   ; 读 others 到缓冲<br><br>     失败 -> 打印 read other failed! 并返回 -1<br><br>缓冲首 4 字节 == 0xFFFFFFFF -> 判定擦除态，直接返回 -1<br><br>循环 strstr 查找 BootImageNum 字符串<br><br>     校验前一字符是逗号或位于串首（记录边界）<br><br>     校验紧随其后的字符是 '=' (0x3D)<br><br>     校验数值后紧跟 ',' (0x2C)<br><br>strncpy(栈缓冲, 数值串, 10)<br><br>simple_strtoul(值, base = 16)<br><br>printf("BootImageNum=%s,%ld")          ; 日志里的 %s 是原串，%ld 是解析值<br><br>cmp  解析值, #0  或  cmp 解析值, #1     ; 只接受 0 与 1<br><br>     其它值 -> 返回 -1<br><br>返回解析值给调用方|

  

三个关键推论。

第一，BootImageNum 是输入而非输出：它被解析、校验、并与常量 1 比较后作为下标返回。

第二，日志里 BootImageNum=0x00000000,0 的含义是原串 0x00000000 解析得 0。

第三，全函数没有任何 nand write、erase 或回写调用，字面量 BootImageNum=0x00000001 仅被送去求字符串长度做缓冲区边界检查，因此不存在“被 U-Boot 自己盖回去”的可能。写回者只可能是 Linux 侧升级代理或产线工具，这与 DownloadState、LastBooting、O7State 三个字段在 u-boot.bin 中完全不存在这一事实一致。

  

七、当前活动槽的判定链

  

判定结论 kernel0 由四重独立证据支撑，任一条单独成立即足以定论。

证据一：日志中 select=0x0 打印两次，  两段算法结果一致为 0。

证据二：entry=2001e0，减去 binheader 长度 0x1E0 得 0x200000，正是 kernel0 的物理起始。

证据三：紧随其后的读操作日志为 (起始地址,上面mtd分区表格有)mtdpartoffset=0x20 0000、 mtdPartsize=0x200 0000，即从 kernel0 起始读整分区。

证据四：内核 cmdline 与 verinfo 行内直接带 0x20 0000 与 u32CurrentSoftNumber: 0，这是 Linux 侧对同一事实的独立记录。

日志中的两行 addr=20 0000 与 addr=220 0000 (kernel0/kernel1 mtd起始地址)是搜索阶段对两个候选各打印一行，不代表都启动；真正被加载的是第二次 select 之后那行 entry 对应的候选。

  

八、切换操作步骤（方案甲，推荐）

  

方案甲只改 others 分区的 BootImageNum 文本，改一个字符，不碰镜像、不重算 CRC、不改标志位。原理是第五节第二段：解析值直接成为最终槽号。

前置检查一条：目标槽 kernel1 的 0x124 必须为 00000000。本机 cmdline 给出其标志为 0x82，bit1 已置位，说明该条件已满足，可跳过实测直接执行。

8.1 第一步：零成本确认无人回写

在做任何擦写之前先做这一步，成本为零，且能一次性证实“改动是持久的”。

|   |
|---|
|U-Boot> mtddebug read 0x43000000 other 0x0 0x20000<br><br>U-Boot> md.b 0x43000000 0x200<br><br>（抄下 BootImageNum=0x0000000X 那一行的 4 个值与偏移）<br><br>U-Boot> reset<br><br>（重启回 U-Boot，重复读一次，比对）<br><br>（再正常启动进 Linux 运行几分钟后回 U-Boot，读第三次，比对）|

三次都不变，说明 U-Boot 与 Linux 侧代理都不回写该字段，后续改动可持久生效。若第二或第三次变了，则说明存在自动写回者，必须先定位它，否则手改无效。原理依据：反汇编已排除 U-Boot 写回，剩下的唯一可能是 Linux 侧升级代理，该实验专门针对它。

  

8.2 第二步：整块读出并备份

|   |
|---|
|mtddebug read 0x43000000 other 0x0 0x20000<br><br>md.b 0x43000000 0x400|

把 md.b 输出完整抄到电脑存档，这是唯一的回滚依据。必须读整块 0x20000，原因见 8.4 的擦除粒度说明。

  

8.3 第三步：定位目标字节并修改

在 md.b 输出里找到 BootImageNum=0x0000000X 这一串，记下 X 所在的确切偏移（下文记为 OFF），然后把字符 0 改成字符 1。

|   |
|---|
|mw.b 0x430000<OFF> 0x31<br><br>md.b 0x430000<OFF> 0x20          ; 改完立刻回看，确认该行已是 ...0x31...|

原理与硬约束：字符 0 的 ASCII 是 0x30、字符 1 是 0x31，必须改的是可见字符本身而不是数值 0 或 1。解析规则要求 BootImageNum 后紧跟等号、数值串后紧跟逗号，两者缺一解析即失败，所以只能改数值位、不能动分隔符。数值按十六进制解析且只接受 0 与 1，写 2 到 f 会让函数返回 -1 并退回标志位初选，表现为改了不起效。另外 others 区首 4 字节不能是全 FF，否则读取器一进函数就判擦除态返回 -1。

  

8.4 第四步：擦除并整块回写

|   |
|---|
|nand erase 0x4200000 0x20000<br><br>nand write 0x43000000 0x4200000 0x20000<br><br>reset|

原理与硬约束：NAND 擦除粒度是 0x20000（128KB），无法只擦一个页，因此必须以整块为单位先整块读出、改内存、再整块擦除回写。若只写一页而不先擦整块，会与原有数据按位与导致内容错乱；若擦整块却只回写一页，同块内其它数据全部丢失。这正是第二步必须读满 0x20000 的原因。

  

8.5 第五步：验证生效

对着串口日志核对四项，全部成立才算真切过去：

|   |   |   |
|---|---|---|
|观察项|期望值|含义|
|第二次 select|0x1|BootImageNum 覆盖生效|
|entry|22001e0|加载的是 kernel1 内镜像|
|mtdpartoffset|0x2200000|读的是 mtd6 分区|
|cmdline 尾部|0x2200000 与槽号 1|Linux 侧确认新槽|

第一次 select 仍为 0x0 是正常现象，那是标志位初选的结果，会被第二段覆盖。若第二次 select 仍是 0x0，则说明目标槽 0x124 不为 0，需按方案乙调整标志位。若出现 magic not found 或 header crc error，说明目标镜像本身不合格，与切换开关无关。

  

九、切换操作步骤（方案乙，备用）

当不想动 others（例如已发现存在自动写回者）时改用此方案：让当前槽让路、目标槽接管优先标记。原理是第一段的 count==2 分支依赖 result[0].flag 的 bit0，而 bit0 来自 0x128。

|   |
|---|
|对当前槽（kernel0，物理 0x00200000）：<br><br>   mtddebug read 0x43000000 kernel0 0x0 0x20000<br><br>   mw.b 0x430000128 0x00<br><br>   mw.b 0x430000129 0x00<br><br>   mw.b 0x43000012A 0x00<br><br>   mw.b 0x43000012B 0x00<br><br>   nand erase 0x200000 0x20000<br><br>   nand write 0x43000000 0x200000 0x20000<br><br>对目标槽（kernel1，物理 0x02200000）：<br><br>   mtddebug read 0x43000000 kernel1 0x0 0x20000<br><br>   mw.b 0x430000128 0xFF<br><br>   mw.b 0x430000129 0xFF<br><br>   mw.b 0x43000012A 0xFF<br><br>   mw.b 0x43000012B 0xFF<br><br>   nand erase 0x2200000 0x20000<br><br>   nand write 0x43000000 0x2200000 0x20000<br><br>reset|

关键提醒：两处必须都改。只把 kernel1 改成 FFFFFFFF 而 kernel0 保持 FFFFFFFF 时，第一段仍会先命中 result[0]，结果是白改。两个字段都在 CRC 覆盖区间之外，不需要重算 Header CRC 与 Kernel CRC。此方案的弱点是它只影响第一段初选，如果 others 里 BootImageNum 仍是 0，第二段仍可能把槽号拉回 0，因此严格来说方案乙需要与方案甲配合，或先确认 others 中该字段被移除。

十、回滚方法

方案甲的回滚最直接：把同一偏移的字符从 0x31 改回 0x30，重复擦写一次即可，镜像从头到尾未受影响。

若曾动过标志位，按备份把 0x128 的 4 字节写回原值同样即可恢复。只有在执行过整块擦除且未先备份的极端情况下才无法回滚，这就是第二步不可省略的原因。

十一、禁止事项与风险

|   |   |
|---|---|
|操作|禁止原因|
|downver kernel 2 等带槽号的子命令|handler 只实现了 boot 与 version 两个分支，其余子命令走到底部直接返回，是空操作|
|sky_bakeup_info writeback|先执行 nand erase 0xf000000 与 0xf400000 各 4MB，再搬移 tag 与 wlan，破坏面远大于收益|
|nand scrub|二进制内的告警原话是会抹掉全部厂商坏块标记，之后跳坏读路径必然错位|
|skfactoryrestore|带等待提示的隐藏恢复出厂命令，非本次目标|
|只改目标槽 0x128|被第二段覆盖，不生效|
|只写一页不整块擦写|与旧数据按位与，内容错乱|
|在其它 0x20000 对齐位置遗留带合法 magic 的数据|搜索函数会把它当第三个候选，打乱 count 判据|
|期待自动回滚|本机没有 altbootcmd、没有 bootcount，写坏不会自愈|

设备一旦写坏不会自动回退，所以任何擦写前先完成整块备份，并保证当前槽处于可启动状态再动手。

十二、OpenWrt 打包脚本改造清单

以下六项均为必改，全部经指令级验证。

|   |
|---|
|1. 0x00 到 0x13 直接复制原厂模板，不生成、不修改、不参与 CRC<br><br>2. 0x58 = uImage 总长（64 字节 uImage 头 + 载荷）<br><br>3. 0x60 = zlib CRC32，区间 0x1E0 到 0x1E0 + [0x58]<br><br>4. 0x110 = zlib CRC32，区间 0x14 到 0x110，长度 0xFC，CRC 字段自身不含<br><br>   顺序：先算 0x60，再算 0x110，不可颠倒<br><br>5. 0x54 与 0x68 = align16(0x1E0 + [0x58])，纯记录用途，U-Boot 不校验<br><br>6. A/B 标志按目标角色写：<br><br>   活动槽 0x124 = 00000000，0x128 = FFFFFFFF，0x12C 继承模板<br><br>   备用槽 0x124 = 00000000，0x128 = 00000000，0x12C 继承模板<br><br>   其余未知字段一律继承模板，不动<br><br>7. 烧写到目标槽后，同步把 others 里的 BootImageNum 设为该槽下标|

镜像格式必须是 Legacy uImage，不能是 FIT，因为校验起点硬编码在 binheader 之后 0x1E0 处的标准 uImage 头。uImage 自身的 Header CRC 与 Data CRC 由 mkimage 自动完成，无需自算。

另有一条来自搜索机制的约束：引导程序不读分区表，纯靠 magic 线性扫描，因此只要把带合法头的镜像放在 0x20000 对齐处就能被收进候选；反过来说，任何残留的旧镜像头都会成为干扰候选。

十三、命令速查（可直接复制）

|   |
|---|
|启动槽现场判定（运行中的 OpenWrt，读加载地址里的镜像头）<br><br># 读优先标记 0x44000128（skip 值 = 地址除以块大小 4）<br><br>dd if=/dev/mem bs=4 skip=285212672 count=1 \| hexdump -C<br><br># 读附加位 0x4400012C<br><br>dd if=/dev/mem bs=4 skip=285212673 count=1 \| hexdump -C<br><br>读出 FFFFFFFF 即 kernel0 在跑，读出 00000000 即 kernel1 在跑<br><br>文件归属复核（确认导出的 bin 与 mtd 编号对应）<br><br>nanddump -f k3.bin /dev/mtd3<br><br>nanddump -f k6.bin /dev/mtd6<br><br>hexdump -s 288 -n 16 k3.bin        # 288 = 0x120，覆盖 0x124 / 0x128 / 0x12C<br><br>hexdump -s 288 -n 16 k6.bin<br><br>md5sum k3.bin k6.bin kernel0.bin kernel1.bin<br><br>反汇编正确姿势（必须用 -D，不能用 -d）<br><br>OBJ=arm-none-eabi-objdump<br><br>$OBJ -D -b binary -m arm --adjust-vma=0x47ee0000 u-boot.bin > full.asm<br><br>自检：wc -l 应有四十五万行左右；不得存在大于 0x100 的地址空洞<br><br>关键函数与锚点（地址 = 0x47EE0000 + 偏移）<br><br>+0x25888  镜像搜索与候选建表<br><br>+0x25b44  BootImageNum 读取器（只读）<br><br>+0x265e0  A/B 选择函数<br><br>+0x2c384  mtddebug 命令实现<br><br>+0x18240  others 分区读取原语<br><br>字面量池  +0x25d08  起，五个厂商串连续排列|

十四、本次未验证或仍有不确定性的项目

第一项，Linux 侧是否存在升级代理会在运行期改写 others 中的 BootImageNum，反汇编只能排除 U-Boot，需要靠第 8.1 节的三次读实验确认。

第二项，0x12C 除了置 bit4 之外是否参与厂商升级逻辑的其他分支，本次只确认它不进 0x82 判据。

第三项，普通内核启动路径是否强制经过 RSA 校验。二进制中确实存在 RSA、SHA、AES 与 efuse 相关代码，但没有观察到本地启动路径上的验证调用，目前按不阻塞处理，属于尚未穷尽的方向。

第四项，search 计数是否可能在只有一个槽有效时仍打印 0x2，本机两槽均合法，该分支未被实测覆盖，不影响当前结论。

  

  

  

附相关资料:  
help mtddebug

mtddebug - mtddebug operate

  

Usage:

mtddebug read - addr partition off size, partitions inlcude boot env kernel kernel1 other and all

mtddebug write - addr partition off size, partitions inlcude boot env kernel and all

    read/write partition 'size' bytes starting at offset 'off'

    to/from memory address 'addr', skipping bad blocks.partitions inlcude boot env kernel and all

mtddebug erase [partition] [off size] - erase partition 'size' bytes from

    offset 'off' (entire device if not specified)., partitions inlcude boot env kernel and all

  

这个 mtddebug 的输出非常关键，但有个坏消息：它只认 boot、env、kernel、kernel1、other、all 这几个固定分区名，没有 mtd12 这种编号，也没有直接列出物理偏移的功能。

  

这意味着什么

  

你的 U-Boot 是高度定制的（ZTE 板子），它把分区抽象成了几个逻辑名字，而不是标准的 mtdparts。mtd12 是 Linux 内核给的分区编号，U-Boot 这边不认这个编号。

  

怎么找到 mtd12 的物理位置

  

你需要先搞清楚 mtd12 在 Linux 下对应哪个名字，然后看这个名字能不能对上 U-Boot 里的 other 或 kernel1 等。

  

第一步：在 Linux 下确认 mtd12 的名字

  

```bash

cat /proc/mtd

```

  

找到 mtd12 那一行，看它的 name 字段是什么（比如可能是 rootfs、data、other 等）。

  

第二步：在 Linux 下查物理偏移

  

```bash

dmesg | grep -i mtd

```

  

或者

  

```bash

cat /proc/cmdline

```

  

看内核启动参数里有没有 mtdparts= 之类的信息，通常会带物理地址范围。

  

  

附补充:  
三、逐格对照：列出顺序 vs 真实顺序

  

/proc/mtd 行序 分区 我累加出的起始 日志真实起始 偏差

mtd1 u-boot 0x00000000 0x00000000 0

mtd2 parameter   tags 0x00200000 0x04800000 列在前、物理在后

mtd3 kernel0 0x00600000 0x00200000 +0x400000

mtd4 middleware 0x02600000 0x05400000 —

mtd5 usercfg 0x02a00000 0x04c00000 —

mtd6 kernel1 0x03200000 0x02200000 +0x1000000

mtd7 others 0x05200000 0x04200000 +0x1000000

  

误差来源可以精确归因：

kernel0 偏 +0x400000 = 被插在前面的 parameter tags 一个分区的长度；

kernel1 偏 +0x1000000 = parameter tags 0x400000 + middleware 0x400000 + usercfg 0x800000 = 正好 0x1000000。

而日志给出的真实物理前段是完全自洽连续的：u-boot 0–0x200000 → kernel0 0x200000–0x2200000 → kernel1 0x2200000–0x4200000 → others 0x4200000–0x4800000 → parameter tags 0x4800000–0x4c00000 → usercfg 0x4c00000–0x5400000 → middleware 0x5400000–0x5800000。每一段的结束地址都精确等于下一段的起始，与 /proc/mtd 的 size 一一对得上——只是排列次序不同。（再往后 wlan / phoneapp / osgi / plugin_data 等我没有逐条核对日志，不写具体值。）

  

四、为什么厂商会同时存在两套顺序

  

/proc/mtd 的行序 = linux内核 MTD 设备的注册顺序，而注册顺序来自硬件厂商 flash table（日志里那句 use normal flash table）这个数组的书写次序。这张表是按功能分组的：引导 → 配置 → 内核 → 中间件 → 用户配置 → 备用内核 → others……

物理布局则是按烧写与扫描效率排的：A/B 两个槽紧挨着（0x200000 / 0x2200000），既方便产线一次连续烧完两个槽，也让 U-Boot 那个"从 0x100000 起、步长 0x20000 扫 magic"的循环天然按地址序得到 result[0]、result[1]。

两套顺序各自都合理，所以会同时存在——这正是这类推断最容易翻车的地方：它不会在总量上露馅，只在顺序上露馅。

  

五、还有一层更彻底的原因：U-Boot 根本不读分区表

  

反汇编事实：搜索函数硬编码起点 0x4010 0000（物理 0x10 0000）、步长 0x20000，逐窗口比对 magic 四字 + header CRC，命中就 append 进 result[] 并打一行 addr=。整个函数没有任何一处解析 mtdparts 或分区表。

由此得到两个重要推论：

result[0]↔kernel0、result[1]↔kernel1 的对应关系，只由物理地址高低决定，与 mtd 编号、与 /proc/mtd 行序都没有因果关系。我第 8 轮的结论之所以侥幸成立，是因为它只依赖"谁地址更低"，而这两行在 /proc/mtd 里恰好与物理顺序同向；凡是依赖绝对地址的操作都会踩空。

同一块区域，U-Boot 日志里叫 mtdpart=0x2，Linux 里叫 mtd3。编号本身就是两侧各自的注册产物，不携带任何语义——用编号或行序反推地址，方法上就不成立。

六、如果当时真按累加值动手，后果是什么（不是"报错"，是"静默毁数据"）

  

  

累加值 实际落在哪 后果

kernel0 = 0x600000 在 kernel0 分区内部偏移 0x400000 处，即内核体中段 擦写毁掉正在运行的系统的内核代码，而 header/magic 一个字节都没碰到

kernel1 = 0x3200000 在 kernel1 分区内部偏移 0x1000000 处 同上，改不到标志位，只毁镜像

others = 0x5200000 落在 usercfg 分区（0x4c00000–0x5400000）内 BootImageNum 一个字节没改到，反而把用户配置分区抹了

三条都是退出码正常、命令"成功"、设备变砖或配置丢失——NAND 的 nand erase/write 不会告诉你地址算错了。这也是为什么这类偏移必须来自打印值，不能来自推算。

七、这类错误的通用防线（建议补进规程）

  

偏移只从"真的会打印偏移"的来源取：启动日志 Creating N MTD partitions、/proc/cmdline 里的 mtdparts=、以及 /sys/class/mtd/mtdN/offset（这个 sysfs 文件直接就是该分区的物理偏移，十六进制，无需任何推算，是运行态最干净的权威源）。

若手上只有 /proc/mtd，必须先证明"行序 = 地址序"才允许累加：读一遍 /sys/class/mtd/mtd*/offset 逐个比对，或至少拿两个已知锚点（如 addr=、entry=）校准。

关键地址至少两条独立通道吻合才算数。本案最终靠四条：日志 addr=200000、entry=2001e0（= addr + 0x1E0）、cmdline 尾部 0x200000 0x0 0x83 0x82、以及内容锚点（该偏移处应读到 99999999 44444444 55555555 aaaaaaaa）。

总量/校验和吻合 ≠ 顺序正确。任何"累加型"推断，都要单独验证它的顺序假设。

八、对已交付文档的影响边界

  

需要修正的只有两个绝对地址：kernel0 0x600000 → 0x200000，kernel1 0x3200000 → 0x2200000。文档里已按正确值写，并显式标注了废弃值与废弃原因。

others = 0x4200000 与日志 mtdpart=0x4, mtdpartoffset=0x4200000, mtdPartsize=0x600000 一致，未受影响。

所有机制结论都未受影响：0x128 优先标记 / 0x124 直选闸门的位级语义、0x12C 只置 bit4、BootImageNum 覆盖初选、两处 CRC 的区间与计算顺序、切换步骤与生效判据（第二次 select=0x1、entry=22001e0、mtdpartoffset=0x2200000）——这些全部来自反汇编 + 启动日志，没有一条依赖 /proc/mtd 累加。

另需说明：第 6 轮"kernel1 是空的"是另一处独立错误（来自被压缩的历史上下文），第 8 轮已作废，与本次地址问题无关。

需要的话，我可以把这一节作为"附录：地址来源与一次方法错误的复盘"追加进那份 Word 规程，连同 /sys/class/mtd/mtdN/offset 的核验命令一起写进去。