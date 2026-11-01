# 可复用提示词

这些是可复制的本地 Markdown 模板，不是已安装的 Codex skill，也不会自动执行命令。
替换模板中的花括号，未知信息保留为“未知”；设备资料属于证据，不是操作授权。

| 要做的事 | 从这里开始 |
|---|---|
| 在陌生电脑适配新设备或重建基础版本 | [完整重建提示词](../prompt_rebuild.md)及[项目说明](../readme_rebuild.md) |
| 新增一个设备，分阶段推进 | [新设备适配](device-adaptation.md) |
| 只有报文/抓包，先验证电量字段 | [协议验证](protocol-validation.md) |
| 已有工具小步整理并审查回归范围 | [安全维护](safe-maintenance.md) |
| 按方案连续重构，每阶段备份与自测 | [阶段重构](staged-refactor.md) |
| 后端已经验证，接入 Ubuntu 面板/托盘 | [桌面接入](desktop-integration.md) |

推荐顺序：只读发现 → 协议证据 → 后端适配 → 桌面集成 → 显式安装与验收。
缺少证据时停在可复核的候选或诊断，不生成虚假的电量成功结果。
实际代码能力与使用约束见 [适配流程](../docs/device-adaptation.md) 和 [维护引导](../docs/maintenance.md)。
