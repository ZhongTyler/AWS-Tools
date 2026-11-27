# 图片上下文预算

按已观察的图片编码大小和接收方日志估算当前窗口预算，只保存大小、会话和工具ID，不存图片或项目正文。Python3.11+，仅标准库；不依赖AWS、meta、作者目录或账号。默认策略20MB提醒、80MB累计上限、20MB单次工具回图，可在policy.json审阅调整。

```text
python guard.py install --codex-home <recipient-codex-home>
python guard.py install --codex-home <recipient-codex-home> --apply
python guard.py status --codex-home <recipient-codex-home>
python guard.py uninstall --codex-home <recipient-codex-home> --apply
```

先准备外部Tools home，使用该固定版本。安装默认预览，--apply才写所选home的hooks.json，保留已有其他处理器；卸载只移除本工具拥有的条目，重复操作保持幂等。包安装不安装钩子，也不会改当前真实客户端；接收方选择home并审阅PostToolUse、UserPromptSubmit、Stop、PostCompact四个处理器的实际命令与源码/策略摘要。变更后重新审查，不绕过客户端信任。

PostToolUse在超过单次或累计回图预算时替换这次工具反馈；已经发生的文件操作等副作用仍存在。被挡图片保持未审状态，可按目标尺寸分批读取；新消息与任务结束只提醒按需留检查点，PostCompact完成后才重置窗口。不自动压缩或改写历史，不创建服务、定时器或模型调用。日志不可用时明确返回unavailable，大小估算仍保留其边界。

适配依据为[官方Hooks文档](https://learn.chatgpt.com/docs/hooks)。托管工具、专用通道、直接附件和客户端版本可能有不同覆盖；本包验证合成事件、临时home安装/保全/卸载与预算行为，没有在接收方真实客户端激活或证明所有通道。不要把结构测试当成实际信任或图片审阅通过。
