# 可审核文案候选

从已有文字生成候选，再对照源身份、数字、引号、代码和完整覆盖检查实际采用。支持网页字段、研究报告与知识正文等通用数据结构；不依赖作者的站点、Research、Knowledge、AWS或meta仓。调用ID是数据用途，输入和采用权归接收方宿主。

Python3.10+，仅标准库。包安装不提供在线模型服务或账号，不读任何默认私人key，不启动服务。离线候选、身份核对与审核无需provider配置。先准备包外Tools home，再经toolbox的相应workflow调用，或直接运行本目录入口。

```text
python run.py candidate game-development --request <request.json> --response-fixture <synthetic-response.json>
python run.py check game-development --request <request.json> --receipt <candidate.json> --reviews <reviews.json>
```

fixture只用于合成数据回归，保留fixture身份；不能代替真实模型输出或上线成功。候选只是待审内容。源/范围/历史提示身份或审核键变化时拒绝；不完整JSON、漏号、重复或未审内容不能进入正文。报告的完整数字、引号及移动关系保持严格保护。

## 显式配置在线调用

仅实现Gemini原生generateContent／streamGenerateContent兼容协议，不宣称支持所有provider。复制provider.example.json到包外私有目录，填写接收方自己选择且获准使用的HTTPS origin、实际model、key环境变量名与已存在的私有diagnostic_root。示例域名不能调用。配置只允许已列六字段，不存明文key；key由调用进程的指定环境变量提供。配置与诊断目录均在不可变包及外部home源码目录之外，拒绝链接路径。

```text
python run.py candidate game-research --request <request.json> --live --provider-config <private-provider.json> --stream --diagnostic-output <private-root>/calls/response.json
```

发送前先由宿主确认选中文本、必要上下文、外发授权和预算，再显式加--live。父目录需由调用方预先建立，诊断文件必须全新。每次只发一条请求、不重定向、超时或不完整返回保留失败；不会自行续呼。模型ID编码后进入URL，凭据及疑似回显不写普通输出，读取超时1–120秒。实际provider连通、计费、隐私政策及质量由接收方验证；本包只做离线替身验证，没有随包在线模型调用或质量承诺。

未配置provider时--live拒绝；不会回落到作者账号、中转站、固定模型或本机诊断根。--relay只能与已配置origin相同。历史提示版本固定，离线检查不套用新提示改签旧证据。[历史身份](HISTORY.md)、[流式合同](STREAMING.md)、[分批](BATCHING.md)沿各自原协议。

## 完整真实响应的后续消费

[原始响应重评](REASSESSMENT.md)用于已证实的机械误拒，必须绑定完整保存调用证据。[作者显式留源](SOURCE-RETENTION.md)用于完整STOP中被明确拒用的保护失败提议：原partial与raw不改，新派生身份绑定作者选择，坏提议不进入有效正文，其他项仍逐项审核。它不修复漏编号、坏JSON或网络无返回，也不批准整篇报告。

真实请求、诊断、作者决定与报告只放接收方私有目录；库内测试均为最小合成材料。安装不外发文本，不创建调度；已有Renderer、版本状态和采用决定继续由宿主拥有。方法润色可按需配合独立Skills，工具不自动安装或调用它们。
