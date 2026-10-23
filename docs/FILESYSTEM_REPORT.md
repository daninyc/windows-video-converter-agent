# 040 文件系统故障与输出保护

测试日期：2026-10-22，北京时间；结果收取确认：2026-10-23。结论：040 本机开发验收通过，**46 passed、0 failed、0 errors、0 skipped**，JUnit 耗时 **55.602 秒**，包括 9 项新增故障场景和 37 项既有转换/路径/取消回归。报告为 `artifacts/reports/filesystem-final.xml`、`filesystem-summary.json`。

## 新增场景

新增 `tests/integration/test_filesystem_faults.py`，9 项场景：

- 实际 Windows ACL 拒绝测试输出目录写入，并在 finally 恢复本测试设置的拒绝规则。
- 在所属尝试的临时写入位置注入 ENOSPC；不填满真实磁盘。返回 DISK_FULL，清理自己的部分文件。
- 源文件在规划后被移走、替换。旧快照不得执行，变化/移动明确返回 FILE_CHANGED。
- 发布前、发布后注入 EIO 中断。发布前不生成结果；发布后结果保留、状态失败并保存实际输出位置，不能清理已发布文件。
- 输出根路径在规划后被替换为真实 junction，指向另一个测试目录。拒绝进入，不在目标处创建尝试目录，不改其中的哨兵文件。
- Windows 大小写等价去重；中文、空格、`[] & #` 字符；读取系统长路径配置并尝试创建超过 260 字符的路径。本机 LongPathsEnabled=0，创建返回 WinError 206，没有进入超长路径实际转码，不能把该子场景描述为成功转换。
- FFmpeg 已完成、输出验证已完成但尚未发布时重复取消，第一项取消无输出，第二个正常样本仍真实转换成功；批次结束再取消返回 false。

每个转换故障场景均检查旧结果和所保护源/替换文件的 SHA-256、不残留自己的临时目录，并在同一批次真实转换、完整解码正常后项。测试不移动或替换共享素材，只使用测试目录中的副本。链接目标和 ACL 操作限定在 D 盘项目测试目录，没有改系统长路径策略、个人目录或全局权限。

## 发现与修复

两个失败先由 `filesystem-first-failed.xml` 真实复现，再修改共用路径：

1. 源文件移走时 FileNotFoundError 原来进入通用 PROCESS_FAILED，误导为进程错误。现在两次执行前/发布前指纹复核共用 `_check_source`，缺失或父目录消失归为 FILE_CHANGED，权限异常仍保留权限语义。
2. 原 `contained_path` 同时 resolve 输出根和候选路径，根本身在规划后变成 junction 时，两者可能同时跳到新目标，无法阻止写出冻结范围。现在 `OutputLease._validate` 先确认已冻结的规范输出根仍解析为自身，再做其余归属/边界验证。

没有更改 no-replace 发布规则，已有目标被抢占时仍避让。既有 `test_output_commit.py` 的真实抢占、已有尝试目录不接管/清理，以及导入链接循环和取消竞态回归一起执行。

第一次广泛回归有 45 passed、1 failed：实际 ACL 拒绝写入的同时也阻止测试读取旧结果，应用已正确返回 ACCESS_DENIED 并继续后项；测试在恢复自身 ACL 前尝试算哈希失败。现在先恢复自身 ACL，再验证哈希；失败报告保留为 `filesystem-first-regression-failed.xml`，不计作通过。

## 复现

```powershell
Set-Location 'D:\CodexWorkspace\bossjinzhoubishiti'
. .\environment\activate.ps1
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest tests/integration/test_filesystem_faults.py tests/integration/test_output_commit.py tests/integration/test_conversion.py tests/unit/test_job_cancellation.py tests/unit/test_batch_runner.py tests/unit/test_output_paths.py tests/unit/test_importer.py -q --fixture-root artifacts/fixtures --data-dir data --junitxml artifacts/reports/filesystem-final.xml
```

本轮仅检验本机 Windows/本地文件系统。长路径是否成功以 JUnit 属性实测值为准，不据此声称所有 Windows、所有路径、网络盘或断电场景都可用。磁盘满与提交中断为隔离注入，没有模拟真实系统掉电或跨资源原子事务。

Ruff 检查和 145 个 Python 文件格式检查通过。46 项是本轮相关回归集合，其中包含先前 Agent 联合报告的既有转换用例，不与那份 145 项相加宣称一次完整联合运行。040 的两个生产修复已在本轮三目标真实转换、批次/取消/重试、提交及导入回归中重新验证。

下一张票为 041 媒体边界。020–039 的独立联合结果与真实 API 未执行的边界见 [AGENT_REPORT.md](AGENT_REPORT.md)。
