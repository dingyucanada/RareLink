# DGX Spark OpenClaw + ComfyUI Workshop 完赛收据

本目录记录赛事组织方新增“跑通参考代码”的基础完赛证据。执行对象为组织方预置的 **OpenClaw + ComfyUI 超级英雄照片生成 Workshop**；它与 RareLink 的医学科研原型是两条独立证据线，不能被解释为临床功能或医学影像结果。

## 已完成的官方流程

1. 在 NVIDIA DGX Spark（GB10、ARM64）执行参考 `workshop.ipynb`，生成独立的 `workshop-executed.ipynb`；26 个代码单元完成，未发现 Notebook 错误单元。
2. 启动本地 Ollama，并用 `qwen3.6:35b` 完成无敏感文本健康检查。
3. 启动 ComfyUI 0.18.1，在官方 FLUX + PuLID 样例工作流上完成一次本地生成；ComfyUI 日志记录 `Prompt executed in 51.87 seconds`。
4. 初始化并启动 OpenClaw 2026.5.19，加载 `superhero` Skill（状态 `ready`）。
5. 通过 OpenClaw 默认 `main` Agent 调用本地 Ollama，得到固定健康检查回复，证明 Agent → 本地模型路径可用。

## 证据边界

- 本收据不含自拍、生成图片、原始提示词、模型权重、Gateway token、IP/端口映射或任何凭据。
- 生成图片来自官方 Workshop 样例，未作为 RareLink 的医学产品功能展示。
- 本目录中的 JSON 仅保留服务版本、完成状态、耗时与无敏感健康检查结果。

详见 [`workshop-receipt.json`](workshop-receipt.json)。
