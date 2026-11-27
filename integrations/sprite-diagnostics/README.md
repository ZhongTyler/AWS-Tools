# 精灵图离线检查 / Offline sprite diagnostics

固定 `@ludoai/cli 0.4.2` MIT 原件，仅通过受控离线适配开放 metrics、loop、slice 和简单等速 Godot 导出，不运行其在线生成、登录、充值等命令。原许可在 vendor/LICENSE，逐文件身份见 upstream-lock.json。需要 Python3.10+、Pillow 与已有 Node24+，不附运行环境或在线账号。

先准备外部 Tools home，在调用者目录用绝对输入/输出路径：

~~~text
python <tools-home>/toolbox.py run --workflow sprite-diagnostics --tool sprite-diagnostics --action health
python <tools-home>/toolbox.py run --workflow sprite-diagnostics --tool sprite-diagnostics --action metrics -- --input <sheet.png> --request <grid.json> --output <new-output-directory>
~~~

`grid.json` 为 `{ "columns":2, "rows":1 }` 等明确布局。输入PNG不超过4MiB、单边4096、4M像素、64格，尺寸需整除。末级输出目录必须不存在，其父目录由调用者先建好。slice保留所有格子；上游把少量尾帧当padding时，诊断/导出拒绝，回原图集路径。

export还需显式 `durations_ms:[200,200]`、`pivot:[54,135]`、`loop:false`。锚点以单帧左上角计像素，输出原色PNG、SpriteFrames、AnimatedSprite2D及最小project.godot副本。变速、事件、碰撞、挂点和正式采用留在项目原流程。

每动作最多20秒。Node使用固定文件权限、最小环境和网络/子进程守卫，只读固定包与任务副本、只写任务副本。原图保全，完成后才公开独立输出目录；失败、超时、已有目录或链接越界拒绝。metrics与脚底/根运动等解释为测量和启发信息，动作/美术质量仍需真实用途审阅。

~~~text
python <tools-home>/integrations/sprite-diagnostics/test_contract.py
~~~

公开测试只覆盖独立producer、像素往返、全部有限动作、预算/失败保全和权限/网络拒绝，不包含私人Studio服务器或下载适配。health核固定文件与Node是否可发现，不启动Node。撤回时切回旧Tools home及原图集入口，保留旧输入和输出记录。

Only the four finite offline operations are exposed. Original vendor files and MIT
license are preserved. Existing Node/Pillow are recipient prerequisites. No online
service, Studio, private asset or artwork acceptance is included. Every result needs
review against the actual intended animation and engine use.
