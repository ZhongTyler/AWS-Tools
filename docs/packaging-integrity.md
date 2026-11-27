# Packaging and integrity / 建包与双层校验

`portable-profile.json` lists the reviewed payload copied by `prepare_home.py`.
`module-files.json` covers the entire immutable distribution, including that profile,
the module manager and wrapper documentation. The portable profile excludes itself
and the outer inventory to avoid a checksum cycle. Both layers retain README checks.

发布顺序必须为：审阅并完成所有源码、便携适配和 README → 显式登记并暂存需要复制的文件 →
刷新便携清单 → 验证便携源 → 封存外层库存 → 验证完整模块。

~~~text
python seal_portable.py
python seal_portable.py --apply
python toolbox.py health --integrity
python .module/module_manager.py seal --apply
python .module/module_manager.py verify
~~~

`seal_portable.py` is a deliberate Git checkout maintenance operation. Its default is
read-only and reports changed members. `--apply` refreshes hashes of the existing
reviewed membership only; it never discovers runtime, changes membership, installs
anything or repairs a consumer's edited files. New payload members require explicit
review, profile registration and Git staging. An outer seal cannot make a stale
portable profile valid. Any subsequent payload edit requires repeating this order.

接收方只运行 verify / health，不运行 seal 来消除差异。模块根与新建外部 Tools home
都应通过 `toolbox.py health --integrity`；外部 home 的运行依赖、账号及模型需另外验证。
包内不放运行环境，准备新 home 不覆盖旧 home。

## Upgrade and recovery / 升级与恢复

2.0.0 的外层库存正确，但 portable profile 保留了包装 README 之前的哈希。
本版按最终文件字节重建内部清单，保留两层严格检查。升级只替换受管理模块源码；
已有外部 home、账号与运行依赖保持独立。先为新版本准备全新 home，按所需工具验证后再切换调用方。
失败时切回旧 home 与原客户端配置。2.0.0 原包的 README 校验失败保留为历史事实；
不要在旧包就地改哈希冒充原发布已通过。
