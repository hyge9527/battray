# 来源与发布许可核对

本文件记录已经识别的参考来源，不替代 LICENSE，也不表示已经取得未确认的再分发许可。发布前需要维护者确认实际采用的代码、数据与文字范围及其对应条款。

## AULA 协议参考

本项目 `keyboard_power/aula.py` 注释所指向的参考：

- 仓库：[Ghost-CR/F75_Initializer](https://github.com/Ghost-CR/F75_Initializer)。
- 文件：[aula_hacky/protocol_core.py](https://github.com/Ghost-CR/F75_Initializer/blob/master/aula_hacky/protocol_core.py)。
- 相关内容：`SESSION_QUERY_OUT`、`SESSION_QUERY_IN` 的报文字节及校验参考。
- 本项目用途：电量查询请求/回复的协议依据；本机 F98Pro 的电量字段另有屏幕实测记录。不是把上游整套初始化或设备配置流程纳入本项目。

2026-10-31 查看了上游默认分支目录、该源文件与 pyproject.toml，本次查看范围内未确认到明确的许可声明。不能因此断言上游必定没有许可证，也不能将“公开可访问”视为已获得任意复用授权。

公开发布前，请完成：

1. 核对实际参考版本/提交，补充固定提交链接，避免只依赖会变化的 master。
2. 区分协议事实/实测数据、独立实现，以及直接复制或改编的代码/文字；当前记录不代替该审查。
3. 核实上游适用条款或取得必要许可，保留其要求的声明。
4. 之后再为本项目选择兼容的 LICENSE。当前不预先标成 MIT、Apache-2.0 或其他许可证。

## 系统组件与可选宿主扩展

Python 工具调用目标系统已安装的 Tk、GIO/GLib、D-Bus 等接口；发布目录不包含这些系统库的二进制副本。可选 GNOME 位置扩展使用 GNOME Shell 提供的接口，不复制或覆盖系统 Ubuntu AppIndicators 扩展源码。

若后续加入第三方代码、图片、字体、图标、抓包或驱动文件，应逐项登记来源、版本、采用范围和许可；不要认为本项目最终选择的许可证会自动覆盖它们。

许可证选择说明见 [GitHub 官方文档](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)。
