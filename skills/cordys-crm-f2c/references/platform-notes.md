# 平台注意事项（Windows / WorkBuddy / Git Bash）

本文件集中维护与运行平台相关的约束。语义文档（SKILL.md、core/*）不再重复这些内容；遇到路径、编码、临时文件或 Python 解释器问题时读本文件。

## 1. 直接调用技能目录内的 CLI

- Windows/WorkBuddy 中直接执行 `scripts/cordys.sh` 与 `scripts/cordys_ext.sh`（建议 `bash scripts/cordys_ext.sh …` 或 Git Bash）；脚本自行处理 Bash → 原生 Python 的路径转换。
- 禁止为了查找 `cygpath` 临时或永久修改 `PATH`，也不要依赖 `.bashrc` 等 shell profile。
- 若仍提示 Python 模块/文件不可访问，按错误中的 `TOOLS_DIR`、`PYTHON` 检查**当前实际运行的副本**是否完整：WorkBuddy 可能调用工作区内的旧副本而不是用户技能目录中的新副本。
- Windows 上 `python3` 常是 WindowsApps 占位程序；可设置 `CORDYS_PYTHON=<真实 python.exe 路径>` 绕过。

## 2. 请求 JSON 的传输

- 查询 CLI 内部生成的 UTF-8 临时 JSON 固定通过 curl stdin（`--data-binary @-`）发送，并由创建该文件的原生 Python 删除。不得改回 `@C:\...` + `rm`：WorkBuddy 会通过 `BASH_ENV` 包装 `rm`，Windows 临时路径识别失败时可能进入回收站降级链路，使一次正常查询额外卡住约 30 秒。
- 调用方只按文档使用 inline JSON 或 `-`/`@-` stdin，不自行管理内部临时文件。
- 子表或其他大 JSON（订单、合同、发票、报价单）必须通过 `-`/`@-` stdin 进入 CLI，不能展开到 Windows 命令行（argv 长度上限）。

## 3. CLI 输出的读取

- 直接读取 CLI 原始 stdout、stderr 和退出码。禁止 `| head`、`| python`、`| grep`，禁止 `2>&1`、`2>/dev/null`，禁止写 `/tmp` 或 Windows 临时文件后二次解析。`head` 会用自己的成功码掩盖上游失败；合并 stderr 会污染 JSON；跨 MSYS/Windows 的临时路径和默认编码（cp936）不一致会把成功输出误判成乱码并触发无意义重跑。
- 管道只允许用于把请求 JSON 送入 `-`/`@-`。
- 平台界面显示"运行成功"但没有 JSON 时，看 stderr 或输出里的 `error`；exit≠0 或有 `error` 即失败，不得当成功。
