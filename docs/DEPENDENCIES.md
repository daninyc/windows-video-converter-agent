# 依赖边界

复用 environment 的已安装版本；锁文件针对 Windows x64 / CPython 3.13。core 是 Qt 与数据校验，tools 是 MCP/检索/数据库/文档读取，cpu-rerank 是独立 CPU 推理。dev 是全部组与测试、打包工具的传递依赖闭包。

锁文件的普通包来源固定为 PyPI，完整版本见 requirements-*.lock。实际下载报告中可核实的 URL 和哈希提取到 dependency-sources.json；预存但未在报告中找到下载来源的包明确标为来源未记录，不补造哈希。CPU Torch 使用 environment/reports/pip-torch.json 中实际下载的官方 wheel URL 与 SHA-256，固定 +cpu，不用浮动 extra-index 替换 CUDA 构建。闭包包含依赖 extras，组间共有包版本一致。

核心启动不导入 tools/cpu-rerank；安装开发组并不代表 GUI 加载全部组件。锁文件是当前平台快照，不承诺其他 Python/平台兼容；本轮未重建一个空白 venv。
