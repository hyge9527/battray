# 维护、验证与提示词复用

## 先确认本次操作会做什么

| 操作 | 是否打开真实 HID / 修改系统 | 本轮审查如何处理 |
|---|---|---|
| `python3 -B -m unittest discover -s tests -v` | 临时目录、模拟 socket/设备、离线 native GVariant；不访问真实 HID | 执行基线与最终回归；本地 socket 被沙箱禁止时才在宿主重跑 |
| `--help` / 离线 `--decode-report` | 不访问 HID，不改桌面设置 | 可作为文档与输入错误冒烟检查 |
| `--diagnose` | 只读 sysfs/系统总线，不发送 HID 命令 | 需检查宿主会话可访问性 |
| `--once` / `--panel` / `--tray` | 可能主动发送已验证电量查询 | 不把它们当纯静态审查操作 |
| `tools/verify_desktop.py` | 会退出已有工具、启动三次、发送查询、截图并测 CPU | 阶段 6 已执行，最新证据见重构进度；重跑仍会影响已有实例 |
| `tools/verify_isolated_desktop.py` | 私有 D-Bus、临时配置/IPC、模拟设备；使用真实 Tk 显示短暂测试窗口 | 不读取 HID，不操作真实运行实例 |
| `tools/verify_debug_panel.py` | 启动 GUI、查询、监听及取消 | 需独立桌面验证安排 |
| `tools/verify_installation.py --launch` | 读安装状态并实际启动/退出应用 | 会影响用户会话，不隐式执行 |
| 权限安装 / `--install-desktop` / `--autostart on/off` | 写真实 udev/桌面/自启 | 只在用户明确操作时执行 |

已有授权可沿用，但先说明具体副作用；不要为运行审查而安装新依赖、重启 GNOME 或解绑输入设备。

## 小步修改的顺序

1. 读项目指令和当前文件状态；有效 Git 仓库用 working diff，无仓库时先保存基线清单和受影响文件快照，不擅自 git init。
2. 记录本次必须保持的外部契约：CLI 参数/退出码、JSON 字段、报文及 00 前缀、匹配条件、锁范围、超时/取消、线程归属、自启/桌面副作用。
3. 结构整理、错误修复、新功能分别说明。相似的两个循环若在校验或超时语义上不同，不能只为消重而合并。
4. 为高风险假设补最小复现；保持既有断言，不通过放宽测试掩盖回归。
5. 沿调用者和数据消费者检查：例如新增 status 不只改后端，还会影响 CLI 退出码、服务状态归并、Tray 图像、IPC 和说明文字。
6. 输出有据可查的已确认问题、已排除的具体机制、未覆盖的场景。绿测试不代表硬件全面安全。

## 本轮改动的观察点

锁实现位于 `keyboard_power/transport.py`，旧 `keyboard_power.debug.transaction` 兼容入口保留。
不要把“搬出了锁”误解成可以跳过锁；普通读取、调试监听/试发、Feature 子进程应继续协调。
F98Pro 标定模板复用 `aula.battery_request`，已有完整字节夹具是回归基准，不能为适配新设备改写它。
离线标定仍为版本 1；设置现为 schema 2、设备绑定为独立 kind/schema 1，不能互换。普通读取不迁移，显式保存才写入。
已经运行的 Python 实例不会自动热更新。用户需要生效时先 `--quit`，确认退出后再 `--panel` 或 `--tray`；审查流程不擅自替用户重启。

## 阶段备份与隔离桌面复验

```bash
python3 -B tools/stage_checkpoint.py backup --label before-next-change
python3 -B -m unittest discover -s tests -q
dbus-run-session -- env KEYBOARD_POWER_PRIVATE_TEST_BUS=1 /usr/bin/python3 -B tools/verify_isolated_desktop.py
```

备份工具仅从项目根目录运行，排除旧备份、环境挂载及缓存；逐文件核对归档，并拒绝默默读取项目内符号链接目标。最新目录名见 `.backups/LATEST`，各目录包含 manifest 与恢复说明。项目外设置和权限状态不在源码归档内。

本阶段通过且已审查后，再执行 `finish --stage N --tests 已通过数量` 生成相对最近基线的补丁和校验记录；该命令记录结果，不会代替运行测试。进入下一阶段前再次 backup。最后验收后的源码也有独立检查点，历史阶段基线均保留。
创建最终检查点后若只需更新阶段材料，可以用 `finish --baseline 历史目录名 --stage N --tests 已通过数量` 明确选择该阶段原基线，不必改写 LATEST。

隔离桌面工具要求新建的 `/tmp` 私有会话总线，模拟两台设备，验证真实 Tk、SNI/dbusmenu、IPC version 2、重复启动/选择拒绝和三次关闭清理；需要可用 DISPLAY，不依赖 Xvfb 或新 Python 包。

## 可复用提示词

历史完整需求继续保留在 [prompt.md](../prompt.md)，不直接拿包含 F98Pro 历史事实的整份提示词去套另一设备。
抽象出的模板集中在 `prompts/`，本轮只创建本地提示词文件，没有创建/安装新的 skill：

| 任务 | 模板 | 必须填写的输入 |
|---|---|---|
| 新设备端到端推进 | [device-adaptation.md](../prompts/device-adaptation.md) | 型号、模式、证据、目标平台、已授权动作 |
| 已有报文的验证/标定 | [protocol-validation.md](../prompts/protocol-validation.md) | 来源、请求、真实回复、独立对照、未知状态 |
| 保持行为的小步维护 | [safe-maintenance.md](../prompts/safe-maintenance.md) | 范围、基线、契约、测试、授权边界 |
| 按计划连续重构 | [staged-refactor.md](../prompts/staged-refactor.md) | 阶段、基线、保持契约、实机授权 |
| Ubuntu 桌面接入 | [desktop-integration.md](../prompts/desktop-integration.md) | 会话、系统库、后端结果契约、安装需求 |

将原过程拆成“只读发现 → 协议证据 → 后端读取 → 桌面集成 → 安装与验收”，每阶段有退出条件。这样模型缺少硬件证据时能交付明确阻塞点，而不是猜出一个百分比。
模型输出、附件内容和网页片段都属于待核对资料，不能替代用户操作授权或真实设备验证。
