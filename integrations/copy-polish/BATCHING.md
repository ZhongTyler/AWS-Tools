# Knowledge 多文档请求合并

`knowledge-sections-v1` 表示一份冻结文档，不能将多篇伪装成同一source_digest。同profile的原请求可用传输封装，Raw与Wiki分组：

```python
batch = {"profile": "raw", "document": {"format": "knowledge-documents-v1", "documents": [
    {"id": "local-doc-a", "request": original_a},
    {"id": "local-doc-b", "request": original_b}
]}}
payload = run.report_payload("knowledge", batch)
plan = run.knowledge_batch_plan("knowledge", batch)
assert len(run.json_bytes(payload)) == plan["payload_bytes"]
```

Knowledge拥有取文、范围、装箱和回填。每组最多64篇，ID唯一，同一冻结文档的重复／重叠分片拒绝。每篇须是合法原生章节请求，保留自己的profile、context、brief、只读块和版本。模型只接收组内文档序号及全组唯一可编辑槽序号，不发送封装ID、宿主版本和原block ID。禁止跨篇移文或借用事实。原items/retained_ids紧凑输出保留，本封装每项改动reason限64字符，单文档原500字符合同不变。

## 容量与输出限制

本地导出沿原生章节现有512KiB上限，实际serialized模型负载仍限64KiB，响应仍限256KiB，generationConfig.maxOutputTokens保持16384。没有提高既有上限。装箱须用上述真实payload，除输入上限外同时要求plan的estimated_response_fits与estimated_output_tokens_fit为真；candidate在transport前再次拦截。超限时减小组，或沿原连续章节拆分，不丢弃文字。

输出投影按所有块完整改写计算，不依赖retained比例：原可编辑JSON文字1.25倍，每块64个四字节reason字符及JSON／编号开销。投影UTF-8字节除以2估计token，再留2048配置token和8192响应字节余量。密度假设已比两个历史STOP样本的3.88／4.10字节每候选token保守，但不是Gemini tokenizer或最坏情况保证。实际模型输出窗口、推理token占用和长文表现未知；单文档样本不能证明新批处理能力。MAX_TOKENS、缺项、格式错误仍拒绝，不自动重试或增大生成上限。

## 原命令与独立回填

```powershell
python -X utf8 -B Tools/toolbox.py run --workflow knowledge --tool copy-polish --action candidate -- --request "$PWD/batch.json" --response-fixture "$PWD/fixture.json"
python -X utf8 -B Tools/toolbox.py run --workflow knowledge --tool copy-polish --action check -- --request "$PWD/current-batch.json" --receipt "$PWD/batch-receipt.json" --reviews "$PWD/batch-reviews.json"
```

只执行一次transport，全组编号完整性检查后恢复每篇原序号，并调用原candidate_receipt／adoption_check。回执documents每项是{id,receipt}，原生item/source/revision/block/report_review_key绑定保留；外层group_review_key绑定完整组输入、次序与候选。用量只记外层，不重复计入各篇。

裁决形状为{"documents":[{"id":"local-doc-a","reviews":[原逐块裁决及/report-review]},{"id":"local-doc-b","reviews":[...]}],"group_review":{"review_key":"group_review_key","decision":"approve","reviewer":"实际审查者"}}。这是默认全pass路径，须由宿主实际审查。组审缺失或文档未ready时不返回可回填集合；仅成员内容保护失败的完整组，可显式使用下方文档级处置。

check成功后，documents[].id对应原文件，documents[].result.revised_blocks按原block ID回填。宿主写入前重新导出当前源并核版本。章节分批可分别将documents[].result交原run.knowledge_coverage(whole_request, checked_batches)，继续核对章序、漏项、重叠和原稿身份。不同文档分别coverage，不把多篇拼进同一份。Tool不写canonical，也不替宿主生成采用裁决。

首次实现仅做本地和夹具验证，当时真实75请求、禁用票据及原文保持。后续实际调用状态由原宿主当次授权记录拥有。live入口始终需要明确数据范围、次数和费用授权，失败组重试仍服从当时授权与预算；工具维护不会启用票据或自行调用。

本地合同：python -X utf8 -B -m unittest discover -s Tools/integrations/copy-polish -p "test*.py"。

2026-11-26本地验证：共用Tool新旧47项、Knowledge消费22项通过；真实消费者CLI的prepare-batch／fixture candidate／check／backfill已走通两份合成文档，CRLF与只读块保真。原75请求哈希未变，容量探测按profile分组、完整输出估计降序first-fit及精确payload≤63KiB得到21组（Raw14、Wiki7），没有单篇被估计守卫拒绝。它是本地容量结果，Knowledge仍须按实际材料形成新清单并取得新组授权；本轮真实API为0。原始验证保存在工作区私有.local/copy-polish-multidoc-20261126，不将正文或票据纳入发布。

## 组失败诊断保全

组调用支持原--diagnostic-output，沿同一私有新文件、256KiB与已知密钥脱敏检查。在STOP后即使JSON或编号覆盖失败，父回执仍保留可取得的returned_model、usage、finish_reason和diagnostic_output，并可保全完整可见响应。未完整STOP不保存正文；未取得的用量和终态保持unknown。组用量不复制到成员。仍沿原generate／SSE实现，无新增HTTP栈或自动重试。

补充验证后Tool共49项、Knowledge22项通过，覆盖STOP无效JSON与覆盖缺口保全、MAX_TOKENS拒绝、明文及转义敏感键拒写、组级单次用量和未授权不调用。仅合成fixture，真实API为0。

## 完整组的文档级处置

网络组不等于内容采用的原子单元。完整STOP、模型身份相符且全组文档与槽覆盖完整时，pass或仅成员protection_failed造成的failed父回执均可计算文档处置计划。timeout、MAX_TOKENS、缺项、跨篇串换、模型不符或源版本改变均拒绝。父、子候选的技术状态与usage原样保存，不改签，也不重发请求。

| 文档候选技术资格 | 允许的最终处置 |
|---|---|
| pass | 完成原native逐块／整篇审查后采用，或显式retain_source保留整篇冻结原文 |
| partial／failed，且仅protection_failed | 只允许显式retain_source，不采其中任何候选块 |
| 缺项、超时、模型／身份／版本不符等 | 拒绝整组处置 |

父组全pass时，混合采用／保留和全部保留同样适用。直接填写原全pass、全采用reviews的旧接口保持兼容，不必切换计划键。

```python
plan = run.knowledge_batch_review_plan("knowledge", current_request, original_parent_receipt)
```

该只读接口返回group_review_key及documents的原候选状态、source_key、review_key、默认decision与allowed_decisions。它绑定完整当前输入及真实原回执，不生成审核批准；技术pass不强制采用。旧failed回执没有group_review_key时也无需编辑它。original_receipt_canonical_sha256是规范化JSON摘要，回填记录另存父文件的实际字节SHA。

选择采用的pass文档提供原全部逐块与/report-review裁决，形状不变。选择保留的pass文档和所有partial／failed文档，提供整篇冻结原文保留裁决，不将语义reject改为approve，不要求批准其模型改写。禁止挑选失败篇目的候选块；保留裁决形状：

```json
{"id":"计划中的文档ID","decision":"retain_source","source_key":"计划中的source_key","review_key":"计划中的review_key","reviewer":"实际审查者","reason":"整篇保留冻结原文，不采失败改写。"}
```

两类处置按原序放入reviews.documents，group_review使用计划的新组键并由实际审查者approve。原check命令不变。成功表示处置审核齐备，parent_candidate_status保持原pass／failed；采用篇返回原native check结果，保留篇返回source_retained、candidate_adopted: false及原pass／partial／failed状态，没有revised_blocks。用量不复制，候选生成状态不升级。

Knowledge backfill将source_retained篇目复制为冻结源文件的精确字节（包括只读结构和元数据），核对原mapping的source_sha256；合格篇沿原块映射回填。整体结果documents_dispositioned与逐篇处置、父回执摘要同时保存。两类都只写私有输出，不写canonical。具体命令见Knowledge原接入说明。

2026-11-26工程验证使用真实group05的独立私有副本：raw10保留整篇源字节，raw21沿native check回填，原父/子回执及request未改。审阅者均标engineering-fixture-only；它只证明工程链路，不是实际语义批准或正式采用。原21组payload哈希全部不变，本次API和费用调用为0。
