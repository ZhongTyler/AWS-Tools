# 本地媒体辅助

`capture.py` 保存指定公开 HTTP(S) 页面和唯一正文容器；动态页面沿浏览器已有渲染路径处理。OCR 仅生成转录、定位候选，图表、条件、数字与动画仍需回看原件。

## 已取得 HTML 的正文候选

~~~text
python toolbox.py run --workflow research --tool media --action body-candidate -- --input-html <saved.html> --url <original-url> --output <empty-directory>
~~~

此动作只读调用者已取得的本地 HTML，不联网、不登录、不执行网页脚本。已知 HTTP 状态时传 `--http-status`。输入上限 8 MiB，拒绝带账号的 URL 和非空输出目录；原 HTML 原字节与 SHA-256、原 URL 留在输出中。

先筛查登录、错误、忙碌空壳与正文不足；放行后用 Trafilatura 2.3.1 提取 Markdown。退出 0 表示候选待审，2 表示回原页核对，1 表示入口错误。缺依赖、版本不符、空提取或异常都保留来源并回退；短文、陌生布局和其他语言的门禁需要人工判断。图注、表格与单位、原链接和关键证据必须回读，候选本身不代表内容已审核或可入库。

Python 3.12 / Windows 可在新外部 Tools home 的 `integrations/media/runtime/body-candidate/` 中按 `requirements-body-candidate-windows-py312.lock` 显式准备可选依赖，不影响 capture/OCR。依赖和安装不随发行包附带；其他平台需接收方验证。

## 指定容器与 OCR

~~~text
python integrations/media/capture.py --url <public-url> --selector <unique-css> --output <empty-directory> --download-images
python integrations/media/ocr.py --output <empty-directory> <image-paths...>
~~~

capture 保存原 HTML、正文、元数据、链接、必要原图与哈希，不携带 Cookie，也不是完整渲染快照。OCR 使用 `requirements-windows-py312.lock` 中的可选隔离运行环境。GIF 的稀疏抽帧不证明动画内容已完整看过。输出、模型、账号及依赖都保存在包外；健康检查不下载、不调用模型。
