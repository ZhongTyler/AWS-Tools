# Tools 2.1.0

本版保持 14 项工具、12 条 workflow，独立使用无需 AWS、meta 或其他模块。
来源冻结为 Tools `2cc7e26b23c725a175a4fd153d375d737914c55c`；逐项采用、保留及延期见 [source-review.json](source-review.json)。

- 修复最终 README 与便携清单的封存顺序；两个校验层都继续严格检查。
- 已取得 HTML 可生成正文候选，缺依赖、版本不符和门禁页面回原页。
- B站音轨/精确帧默认 600 秒，可显式扩展至 3600 秒，40 MB、匿名访问和时限不变；保留原发布时间，未知更新时间仍为空。
- 知识反馈可凭 owner 结果、验证引用和采用/入库证据闭合，保留证据并退出候选选择。
- 排盘可直接使用调用者已确认的校准钟点，节气附近拒绝，起运日期标为暂估；不自动校时。
- 安装器遇现有受控 HN/RSS 配置即停止，保留原配置。

本地素材新 schema2 和相邻工作室链留到独立素材批次。新模型、运行环境、账号、采集物与维护者项目样本未收录。
现有许可、固定原件和公开专用适配保留。只读/合成验证不能证明接收方联网、推理、艺术效果或项目采用。

## Upgrade / 升级

2.0.0 → 2.1.0 是兼容增量；旧动作与 workflow ID 不变。HTML 正文候选为新增可选动作。
先升级管理模块，在新位置运行 `prepare_home.py`，再按需要显式配置该外部 home。
不要覆盖旧 home；失败时切回旧调用方配置与旧 home。包升级/恢复不迁移账号、模型或输出。
原 2.0.0 README 内层校验失败的证据保留，不追改旧 tag。

The 14 tools and 12 workflows retain their existing IDs. This release adds optional
local-HTML extraction, bounded Bilibili duration/metadata, evidenced feedback closure,
explicit caller-corrected clock handling and shared-configuration protection.
Prepare a fresh external home and validate only the selected runtime; rollback by
restoring the previous home and caller configuration. No runtime, account, model,
private sample or automatic activation is supplied.

`_release.json` and the original `sources.json.entries` describe historical export
inputs. They are not the current release authority. `module.json`, `module-files.json`
and `docs/source-review.json` define this standalone release and its reviewed changes.
The complete package is not an offline mirror of every optional dependency.

## Feedback data rollback / 反馈数据回退

2.1.0 能读取旧记录，但显式调用 `resolveIssue` 会写入旧 2.0.0 reader 不认识的
`resolved` 状态。同一 store 写入此状态后，直接切回旧 reader 会拒绝，不能把数据回退
等同于包文件回退。启用新写入前保留宿主批准的 store 快照，或使用独立 namespace/home。
需要回退时保留新 store 原件；选择继续使用新 reader，或在另一位置恢复升级前快照，
再切换旧 reader。后续新证据仍留在新 store 待 owner 处理，不删改日志以适配旧版。

The new reader accepts old records. Once `resolveIssue` writes `resolved`, the 2.0.0
reader rejects that store. Retain the new data. Use the new reader, or restore a
pre-upgrade snapshot into a separate location/namespace for the old reader. Restoring
package files alone does not roll back feedback data. No migration edits are automatic.
