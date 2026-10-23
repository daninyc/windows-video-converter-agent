# 桌面视觉基线

2026-10-21 阅读 Spec 指定的 [WinUI Gallery](https://github.com/microsoft/WinUI-Gallery) 和 [QFluentWidgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets) 项目介绍及演示。采用的是工具窗口的分区规律：浅色背景、清晰标题、主工作区与参数区分开、底部持续显示执行状态、辅助内容停靠且可浮动。实现全部使用 PySide6 Qt Widgets。

WinUI Gallery 的[仓库许可](https://github.com/microsoft/WinUI-Gallery/blob/main/LICENSE)为 MIT；QFluentWidgets 的[仓库许可](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/blob/master/LICENSE)为 GPLv3。这里只参考布局规律，没有复制源码、图片、图标或样式文件，没有安装这两个项目。自身源码与最终分发组件的许可清单仍由收尾票核验。

当前实现左侧任务列表与详情、右侧参数、底部进度及操作、AI 停靠区。浮动和隐藏实际可用；导入、参数编辑、转换和聊天在相应核心票实现前禁用并说明原因。空态显示未知信息，不用演示数据冒充探测结果。最小逻辑窗口 1080×720，参数区支持滚动。

三档截图命令：`python -m media_converter.devtools.capture_shell --scale 1 --output artifacts/ui/shell`，分别用 `1`、`1.5`、`2` 执行。每档使用单独进程和真实 Windows Qt 插件，通过 `QT_SCALE_FACTOR` 验证缩放；不修改用户系统显示设置。屏幕、DPI、窗口逻辑尺寸、截图像素尺寸记录在同目录 JSON。该检查仅覆盖基础布局，不能代替 tickets047 的最终交互验收。

本机系统原生缩放为 125%，脚本用 Win32 获取系统基准 DPI，再调整独立子进程的 QT_SCALE_FACTOR，使实际 DPR 分别等于 1、1.5、2；自动测试核对实际值和截图像素。截图子进程隔离无关 PATH，退出前释放窗口。最终三档图片已目视检查，最小窗口参数区使用纵向滚动，不横向遮挡。
