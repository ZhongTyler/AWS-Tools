# 保存响应的机械重评与返回契约

原 live partial 永远保留。这个入口读取同一次保存的完整 STOP 响应，在新的保护检查版本下生成独立候选，mode 为 `live_response_reassessment`；它不是新 live 成功，也不是 fixture。原 usage/cost 是父调用的继承信息，不代表本次新增消耗。此入口不联网、不读密钥、不调用模型、不写原稿或原回执。

## 输入与身份

显式 bundle 包含 `workflow` 和 `inputs`，后者恰好有8项绝对JSON路径：`request`、`original_receipt`、`diagnostic`、`payload`、`host`、`execution`、`started`、`literal_inventory`。

- 仅接受原生 `live`、`partial`、已保存 diagnostic、完整 STOP，且返回模型、传输版本、usage相符。
- 启动记录的原request文件SHA、执行记录的开始时间/原candidate路径/export目录/status/退出码/usage逐项绑定。
- 保存的准备payload按其host.document验证；原candidate的实际document按已登记提示版本验证，两者分别记录，不能把准备payload称作实际HTTP抓包。没有独立wire捕获时明确unknown。
- 用原保护规则重解析同一raw，必须完整复现原partial的全部字段；再在源绑定清单下重算。原raw文字、source_key、scope和brief不替换。
- 8份文件路径与原字节SHA、raw文字SHA、保护契约版本写入新派生身份。每次原生adoption_check都重新核这些文件、重建候选，候选或证据变化即拒绝。

~~~text
python -X utf8 -B Tools/integrations/copy-polish/reassess_report.py --bundle <private-evidence-bundle.json> > <new-derived-candidate.json>
python -X utf8 -B Tools/integrations/copy-polish/run.py check game-research --request <original-request.json> --receipt <new-derived-candidate.json> --reviews <current-owner-reviews.json>
~~~

输出0仅表示机械候选覆盖与保护通过，采用仍需当前owner逐项及整篇审阅。旧partial和新派生文件同时保留。`--payload` 仅在payload属于candidate自身身份时使用；历史prepare与实际候选版本不同的情况由bundle分别验证。

Python消费者可调用 `reassess_report.build(api, workflow, paths)` 和 `reassess_report.verify(api,workflow,current,receipt)`，api 为 `SimpleNamespace(**vars(copy_polish_module))`。`adoption_check` 自动识别派生模式并回填该证据。外部宿主如有mode/字段白名单，需要按这一准确模式适配，不能改成live或丢掉派生身份绕过。

## 显式字面量清单

`literal_inventory` 的 `contract_version` 为 `literal-boundaries-v2`，`status` 为 `maintenance_reviewed_literal_boundaries`，并提供 `source_id`、`source_text_sha256`、`literal_counts`、`numbers`。清单须由宿主明确审阅，不能从候选反推。它只为该源字段消除已证实的分词误报，不是任意override。

原文字节SHA和每个字面量/数字的原出现次数必须相符。候选中的路径与标识符须完整、明确分隔，不能仅是更长Unicode目录或标识符的子串。长项先处理重叠；原始总次数独立严格检查。没有明确候选边界则拒绝，未声明内容仍用原保护检查，数字/引号/代码真实变化仍拒绝。语义新增、因果和身份改变继续由owner对照来源审阅。

## 返回策略1.2.0

新候选的 `report_response_policy: "1.2.0"` 标明新解析策略；该可选字段需外部宿主白名单准确接入。新提示登记为1.2.0；1.0.0和1.1.0原文保持。新提示强调原数字/路径/标识符和原引号内容逐字逐次保留，不新增引号/人物身份，并明确JSON转义和编号全覆盖。实际模型遵循效果须由获准的新调用检验，离线测试不证明它已经改善。

仅新策略将compact items中与原槽逐字相等的行按留源分类，reason声称移动不能代替实际改动。noop附moves_from或未知字段、缺失/重复/未知编号仍拒绝。旧策略仍拒绝report_edit_unchanged。Golf式坏JSON不猜修；Mort式新引号仍保护失败。Hook跨批scope必须不重叠、顺序和完整revision/brief一致，额外语义缺口不能冒整篇通过。

## 恢复

本次维护只修改固定执行器、保护与提示版本、回归和文档。撤回代码不改旧回执或原稿；派生文件要连同其8份固定证据保留。未来变更不得热改已登记提示或保护契约的含义。未通过新检查的响应保持原失败，不自动重呼或扩大预算。
