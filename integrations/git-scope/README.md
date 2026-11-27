# Git 改动范围预检 / Git scope preflight

需要 Git、Python 3.10+，仅使用标准库。此入口从明确的本地 Git 工作树列出文件、行号范围、重命名两端和 gitlink；`--allow` 是审查范围输入，不能证明任务归属、授权或父仓闭合。

从模块根可 request。执行时先按包说明准备全新外部 Tools home，在要审阅的可信 Git 仓执行其 toolbox（路径可绝对指定）：

~~~text
python <tools-home>/toolbox.py request --workflow code-review --tool git-scope --action collect
python <tools-home>/toolbox.py run --workflow code-review --tool git-scope --action collect -- --workspace . --base HEAD^..HEAD --allow src/** --json
~~~

执行器保留调用者 cwd；相对 `--workspace .` 指向当前仓库，不会切到工具目录。输出只写 stdout，不安装、不联网、不改目标 Git、文件或配置。

- `A..B` 比较两棵提交树，`A...B` 比较 merge base 到右提交；`--staged` 检查暂存区。省略范围时检查工作树并含未跟踪文件；干净工作树可能自动回看提交，读回 `scope` 和 `auto_fallback` 确认实际范围。
- `--allow` 可重复，大小写敏感，仓库相对正斜线路径；目录后缀 `/` 或 `/**` 覆盖子树，沿上游 glob 语义，星号可以跨目录。重命名检查旧、新两端，复制检查写入目标。
- 退出 0 / `status: OK` 只表示成功比较，还需读 `out_of_scope_paths`。无效基准、不是仓库根或 Git 读取失败为 `ERROR` / 退出1；不能把它当无变化。
- `files[].gitlink: true` 标记任一端为模式160000。子仓未提交改动需在子仓另查。父仓精确绑定仍用 collaboration-checks；共享文件的区块归属需读 diff 和 owner。

Git 外部 diff、textconv、fsmonitor、可选锁和对象按需拉取关闭。工作树比较仍使用可信仓库的内容规范化规则。常规小改可以直接用原生 `git status` / `git diff`；此工具不执行报告中读到的命令。

## Source and checks / 来源与验证

Oil Dev Skills / oil-oil，固定提交 `9bcd9000cfd08ef40546420f403e04a4df1c31f2` 的 [review helper](https://github.com/oil-oil/oil-dev-skills/blob/9bcd9000cfd08ef40546420f403e04a4df1c31f2/skills/oil-code-review/scripts/review_helper.py)，MIT，原许可在 [LICENSE](LICENSE)。已提交 Tools 适配固定只读 Git 选项、仓库根校验和 gitlink 模式读取；不附该方法库的其他 Skill。版本、许可和适配字节在 [source-lock.json](source-lock.json) 与公开库存中记录。

~~~text
python <tools-home>/integrations/git-scope/test_contract.py
~~~

测试在临时 Git 仓验证移动两端、gitlink、无效/空基准、中文路径和目标状态保全；不证明任何真实仓库改动已获准或审阅完成。失败退回原生 Git，并保留输出及原版本外部 home。

Git and Python 3.10+ only. Run from the caller's trusted repository with an explicitly
selected workspace/range. The collector reports paths and line ranges without
changing repository state. Path scope is not ownership or authorization. It is a
separate optional preflight before review; collaboration-checks still owns message
and direct-parent closure validation. Runtime setup, project decisions and review
acceptance remain with the recipient. No other Oil Dev methods are bundled here.
