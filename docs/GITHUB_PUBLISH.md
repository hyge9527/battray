# GitHub 发布拆分与操作顺序

## 1. 先用一个仓库，按用途分区

仓库名：`battray`，地址：https://github.com/hyge9527/battray。建议描述：

> Ubuntu wireless peripheral battery monitor with a Python stdlib/ctypes core, verified AULA F98Pro support, and guides/prompts for adapting new 2.4G devices.

当前源码与提示词共享同一套真实接口、约束和设备证据，先放一个仓库更容易保持版本一致。不要为了“拆分”现在移动 Python 模块或改脚本路径，否则会影响导入、桌面链接和自启。

| 分区 | 内容 | 给谁看 |
|---|---|---|
| 项目门面 | README.md | 第一次访问的人：用途、支持范围、运行入口 |
| 使用与实现 | keyboard_power/、my_devices.py、docs/ | 用户与开发者 |
| 重建与迁移 | readme_rebuild.md、prompt_rebuild.md、prompts/ | 在另一台电脑适配新设备的人 |
| 平台安装 | packaging/、安装工具 | 明确需要权限/桌面集成的人 |
| 可选 GNOME 组件 | packaging/gnome-tray-position/ | GNOME 46 的固定排序需求，不属于通用设备后端 |
| 验证与贡献 | tests/、CONTRIBUTING.md、Issue 模板 | 贡献者和维护者 |
| 来源与授权 | THIRD_PARTY_NOTICES.md、后续确定的 LICENSE | 所有复用者 |

以后只有当“通用适配提示词”已经独立维护、面向多项目时，再拆出独立提示词仓库，并用版本链接引用代码。GNOME 扩展若独立发布到扩展平台，也可另建仓库；现在不用先维护三套版本。

## 2. 公开源码与本机资料分开

不上传：`.backups/`、`.publish/`、缓存/虚拟环境、`.env`、生成的 `local.keyboard-power.desktop`、临时审查 JSON/patch，以及用户设置、原始报文采集、私人截图等。本机启动器包含绝对路径，由安装器在目标电脑重新生成；不要为发布删除它，本机桌面链接还在使用。

`docs/refactor-progress.md` 等历史文档可保留为开发记录，但其中本地备份路径和成绩不是下载后的测试结果。公开包不携带本机备份或原始验收截图。测试中的 `/dev/hidraw7` 是临时夹具数据，不能只凭字符串出现就删掉测试。

`.gitignore` 只影响未跟踪文件；如果文件曾提交，它不会自动从历史或远程消失。发布前核对实际暂存列表，不能把“配置了 ignore”等同于完成了隐私审查。

## 3. 当前许可证事项必须先核对

当前没有 LICENSE；`aula.py` 明确参考了上游协议文件，本次未确认其具体许可。请先完成 [来源记录](../THIRD_PARTY_NOTICES.md)中的核对，再选择项目许可证，不要在 GitHub 创建页直接随手选择 MIT，也不要在 README 宣称已开源授权。

如果先备份到 GitHub，可以先建私有仓库供审阅，但私有并不能替代来源/再分发权限核对。公开可见与授予开源复用权是两回事；参考 [GitHub 许可证说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository)。

## 4. 生成独立上传副本

在当前项目根目录运行：

```bash
python3 -B tools/prepare_github.py
```

它只复制明确的源码/文档分区到新建的 `.publish/github-时间戳/`，不改变运行项目、桌面链接或自启，不初始化 Git、不创建远程、不上传。旧发布副本不覆盖；根据输出进入新目录。副本内的 `PUBLISH_MANIFEST.json` 是本地核对清单，默认不入 Git。

生成过程不是通用秘密扫描器。仍需人工查看新增/修改文件、来源声明和文档中个人信息；补充 LICENSE 后，重新导出或把已确认的 LICENSE 放入该副本。

## 5. 在副本检查与提交

原项目的 `.git` 是只读占位目录，不要在那里强行初始化。在刚生成的发布副本中操作；下面命令只作为手工步骤，本次准备没有替你执行。

```bash
git init -b main
git add .
git diff --cached --stat
git diff --cached --name-only
git diff --cached
```

核对没有本机启动器、备份、凭据、未经脱敏的图片/抓包；确认来源与 LICENSE 后再提交：

```bash
git commit -m "Initial source, device adapter and adaptation guides"
```

在副本中做隔离测试需要系统 Tk/GIO 等现有组件；Python 没有第三方 pip 运行依赖。不要运行权限安装器或启用 GNOME 扩展作为发布检查。

```bash
python3 -B -m unittest discover -s tests -q
```

可选扩展模型检查：`node tests/test_tray_position.mjs`。Node 只是开发检查工具，不是主应用运行条件。

## 6. 创建 GitHub 仓库并推送

先在 GitHub 创建空仓库，选择所有者、仓库名和可见性。因为本地已有文件，不要在创建页额外初始化 README、gitignore 或 LICENSE，以免产生两套初始提交。认证使用自己的 SSH 或 GitHub 支持的认证方式，不把令牌写入仓库或远程 URL。

本项目的远程地址如下（SSH 需要先配置 GitHub SSH 认证）：

```text
git remote add origin git@github.com:hyge9527/battray.git
git remote -v
git push -u origin main
```

若已存在 origin，先检查它，不直接覆盖或强推。上传完成后检查 GitHub 首页能否读懂用途、支持范围和新设备流程，确认文件列表没有本机资料。

操作依据：[GitHub 官方：上传本地代码](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)。上述命令中的仓库名、账户、许可证与可见性由维护者确认。

## 7. 首次公开版应说明什么

- 平台是 Ubuntu；真实硬件支持是指定 F98Pro 接收器配置，不能叫“所有 2.4G 设备通用电量驱动”。
- 框架支持继续添加适配器，未知设备需要独立协议证据；绑定 JSON 不会自动逆向设备。
- 标准 HID Feature 解码和多设备模拟通过的范围，与真实硬件认证分开写。
- GNOME 固定排序是可选的 GNOME 46 组件，需要宿主侧安装/实际登录验证。
- 测试数与 CPU 数据有日期和环境，不承诺在别人电脑上复现同一个数字。
- Issue 中的设备报告需要哪些字段、如何脱敏、哪些设备操作不应该盲试。

首次发布先保持源码仓库；没有必要立即上传可执行文件、安装未知系统包、添加自动发版或启动 GUI/HID 的 CI。后续 CI 优先覆盖隔离单元测试与离线解析。
