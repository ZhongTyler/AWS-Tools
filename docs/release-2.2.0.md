# Tools 2.2.0

本版保留既有14项工具，新增3项独立入口，共17项工具、15条可选workflow。没有模型、账号、私人项目、报告或已安装运行环境。

|入口|可实际执行的内容|接收方条件|
|---|---|---|
|git-scope|Git范围、重命名两端、gitlink和越界路径只读预检|Git、Python3.10+，可信仓库|
|sprite-diagnostics|PNG metrics/loop/slice及简单等速Godot副本导出|Pillow、Node24+，明确布局与全新输出|
|demo-support|参数面板、通用离线样例、已有音频片段与循环候选；health只核源|浏览器/Node；音频另配Python3.11+/NumPy/SoundFile|

逐项来源、原件保全、许可和便携适配见 [source-review-2.2.0.json](source-review-2.2.0.json)。
Git helper仅从Oil Dev固定提交取执行器；Ludo0.4.2和lil-gui0.21.0原件及MIT许可保留。方法型内容仍按Skills归属审核，本机安装不等于已在AWS-Skills42项中公开。

## 升级与恢复 / Upgrade and recovery

2.1.0→2.2.0为新增可选入口，旧14项动作与现有数据约定保留。先升级管理模块，在全新包外home准备版本化源码，再验证需要的运行依赖并切换调用方。保留旧home与配置，失败切回；不迁移账号、模型、项目预设、音频或用户仓库。

同时修复body-candidate继承工具目录导致调用者相对HTML/输出路径失效的问题；现在保留调用者cwd，与源实现一致。

Git预检不证明任务归属或授权，精确父仓闭合仍沿collaboration-checks。精灵测量与音频解码不替代动作/听感和实际引擎验收。参数样例验证独立面板，不代表任何游戏已接入。本轮独立合成验证不继承私人项目/画室的艺术验收。

copy-polish的源保护修复已完成，但尚需账户无关的公开服务/模型/凭据配置及诊断目录适配；本批不复制私人默认relay或真实报告。animation-review缺少独立分发许可，Docling共享依赖METADATA未通过；这些各保留明确资格，继续单独维护。

This compatible release adds three optional CPU-oriented tools: Git scope preflight,
finite offline sprite diagnostics, and reusable demo parameter/audio support. Existing
14 tools remain. Prepare a fresh external home and configure only selected runtime
requirements. Roll back to the previous module/home without rewriting user data.
All third-party originals and licenses are preserved. Offline tests do not constitute
project, animation, listening or user acceptance. No model or service calls are made
by installation or health checks. The feedback resolved-data rollback limit in
[2.1.0](release-2.1.0.md) still applies.
