# SSE终态与原文保留

## STOP后的尾部

transport 1.1.5将完整SSE事件里的STOP作为模型终态，在该事件内容校验后保留正文检查点。随后最多读取1秒尾部，接收可能跟随的usage/model事件；心跳不会重置绝对截止。正常EOF仍走原严格传输检查。若连接一直保持，到期关闭读取，以实际已收到的完整候选继续JSON、编号覆盖、保护和语义审核流程，回执标记transport_completion: stop_tail_deadline。这个标记不保证用量完整，未收到的费用仍unknown。

STOP本身不证明候选合格。缺项、无效JSON、保护失败、MAX_TOKENS、第二候选、流错误、敏感键及256KiB上限继续拒绝。没有STOP时仍沿原45／120秒单次阻塞I/O超时和失败路径，不自动重试、不换relay、不返还调用预算。

严格HTTP截断或其他传输失败仍返回failed；若此前已经收到完整STOP，候选入口保留该检查点中实际取得的模型和用量，并沿原--diagnostic-output保存实际可见正文供离线复核。该诊断不把失败变成完成，也不替代源和语义审查；同样执行私有新文件、大小及已知密钥拒写。单文档和多文档组复用同一实现。

2026-11-26 Hexcells故障的历史第二批：收据为STOP／reading_sse timeout，187项无text，stderr为空且diagnostic-2.json未创建。旧版在等EOF时抛错，正文局部变量未进入持久化入口。在当前任务目录和工具持久化入口中不能恢复这份真实正文；不能用原输入或合成夹具冒充模型输出。旧回执、五次已用预算和费用unknown保留。本次未新增模型调用。

本机HTTP故障回归覆盖STOP后保持连接、持续心跳、120秒连接超时配置下的一秒绝对尾部截止、尾部用量保留、严格HTTP断尾失败及实际检查点诊断。真实relay上的新行为尚未验证。

## 完整返回后显式保留送审原文

普通decision: reject继续拒绝整批。仅research-report-edit-v1完整STOP/pass的候选新增可选decision: retain_source，用于拒绝某条已完整返回、通过机械保护检查的改写，并采用同次送审原文。它不会改原live候选，也不能覆盖missing、timeout、protection_failed、部分覆盖或新版本源。

逐项裁决保留候选原id与review_key，另给当前source_key、实际reviewer和具体reason：

```json
{"id":"原稳定字段ID","review_key":"原候选review_key","source_key":"原候选source_key","decision":"retain_source","reviewer":"实际审查者","reason":"候选新增全称判断，保留本次送审原文。"}
```

其他条目仍逐项approve，/report-review仍用原完整候选report_review_key。宿主确定所有逐项裁决后，在工具目录导入run，计算：

```python
key = run.retained_source_review_key(workflow, current_request, original_receipt, reviews)
whole_review["retained_source_review_key"] = key  # whole_review就是reviews中的/report-review
checked = run.adoption_check(workflow, current_request, original_receipt, reviews)
```

这个键绑定完整当前输入、不可改的原候选，以及所有retain_source裁决（含原因、审查者和原键）。生成键只用于绑定，不授予审核权限。改变源、候选、保留范围或理由后，旧整体键失效，须按原审核流程重审。CLI check命令不变。

成功回执按实际采用文本返回revised_source与原映射，保留项明确记录decision、disposition: retained、candidate_review_key及新review_key，另保留original_report_review_key与retained_source_review_key，区分模型候选和审查后的原文选择。它不能作为未返回章节的补齐，也不改变原有发布、账号或写入授权。

历史报告提示、保存 payload、原生审核与宿主 verify／plan 的兼容入口见 [HISTORY.md](HISTORY.md)。prepare 时身份和候选身份分别校验，旧回执不按当前提示重写。
