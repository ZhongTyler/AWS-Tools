# 完整真实响应中的作者拒用

`source_retention_report.py` 只消费已保存的完整 STOP 报告响应。原 live partial、raw、请求、诊断与调用记录不改；新 mode 为 `live_response_source_retention`，不是一次新模型调用，也不是把原失败签成成功。

bundle 使用 workflow 和 inputs；inputs 必须为八个绝对 JSON 文件路径：request、original_receipt、diagnostic、payload、host、execution、started、author_decisions。前七项沿原 saved-response 身份核验。作者决定文件 schema_version 为1，含 workflow、status、request_sha256、original_receipt_sha256、diagnostic_sha256、decisions。每个决定需精确 id、source_key、rejected_candidate_text_sha256、decision=retain_source、reviewer 和 reason；必须覆盖全部且仅覆盖 protection_failed 槽。可另附 author_decision_origin 的 path/sha256，原作者决定也须逐字段匹配，不能用来源链接代替裁决一致性。

```text
python source_retention_report.py --bundle <private-bundle.json>
python source_retention_report.py --bundle <private-bundle.json> --required-reviews
```

第一条输出新的机械合格待审候选：被拒用槽取源文本，其余槽保留真实模型文本。完整有效文字重新走原数字、引号、移动与覆盖保护，仍失败就拒绝。第二条仅返回已明确留源项的必需 review 字段，不批准其他项。调用方将这些字段与其他逐项语义决定、完整报告审核一并交原 `run.py check`。完整报告还绑定 `retained_source_review_key`；不能把仅三项决定当整篇通过。

原生 check、checked_report_identity 会重新读取八份证据及可选原作者决定，完整重建派生身份；来源漂移、伪造候选、缺项/重号/多项、坏JSON、非STOP、未列明失败、不同槽复用裁决、作者决定漂移都拒绝。Research原有plan通过checked_report_identity消费该身份，返回response_derivation；不需改写原export或伪装live。生成plan仍待原renderer及业务审阅。

证据路径和正文由宿主放在私有目录，不随公开包或fixture分发。本入口不处理网络无返回、格式失败、漏编号或未知失败，不修正文、不启动服务、不调用模型。默认候选、已有合法retain_source和原saved-response重评保持原合同。
