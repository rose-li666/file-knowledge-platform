# M2 实测报告

状态：M2 已完成。应用内和容器真实 HTTP 均验证 10/10 份资料上传/下载 SHA-256 一致；浏览器上传、详情与下载由用户在本次消息手动确认。编码修复有独立本地回归证据。

## 改动范围

- 新增 documents 元数据表，独立业务数据库 `/data/db/platform.sqlite3`；原文件保存 `/data/uploads`，使用随机键防止同名覆盖。
- 上传以 multipart 接收一个文件；默认 20 MiB，可配置。原始字节不转码；计算 SHA-256、fsync、持久化意图、原子改名、提交元数据，提交成功后返回 201。
- GET 列表（分页）、详情、原文件 attachment 下载；下载前验证大小及哈希；分类响应 null，正文/向量状态 not_started。
- 页面多文件顺序上传、XHR 实际进度与正在保存状态、逐文件错误、列表加载/空状态/刷新、完整详情与下载反馈。
- 分类、归档、检索、任务恢复、去重和故障注入没有提前实现。

## 实际执行

```powershell
& '.\work\m1-venv\Scripts\python.exe' -m pip install --no-compile --retries 1 python-multipart==0.0.20
& '.\work\m1-venv\Scripts\python.exe' 'outputs\platform\scripts\verify_m2.py' --zip 'D:\__10_.zip' --data-dir 'work\m2-data' --report 'outputs\m2-local-results.json'
```

- 固定版本 multipart 依赖安装退出码 0；安装时使用已授权网络与 work/tmp 临时目录，未修改 PowerShell 执行策略。
- React/TypeScript/Vite 构建退出码 0，28 模块；已生成 HTML、JS、CSS。未将构建成功视为浏览器验收。
- 资料校验退出码 0，10 份真实原文件与下载字节逐一比较并核对 SHA-256；总耗时 101.676 秒，包含本地模型启动，不是单文件上传耗时。
- 本地 Uvicorn 日志显示启动完成，但跨工具 TCP 请求超时，已停止该临时服务器。不能以进程启动声称 TCP 通过。

## 原文件 / 下载 SHA-256

下列来自实际上传、详情读取、下载和磁盘核对。传输为 **in-process ASGI TestClient**；不是容器 HTTP 或浏览器证据。

| 文件 | 字节 | 原文件 SHA-256 | 下载 SHA-256 | 结果 |
|---|---:|---|---|---|
| 01_代码提交规范_v2.1.md | 3131 | `4db0b06b4701f5b22aa03a8ee8f6bf1eb2cd6fc4f66fafce46a2255aeb09a599` | `4db0b06b4701f5b22aa03a8ee8f6bf1eb2cd6fc4f66fafce46a2255aeb09a599` | 一致 |
| 02_发布检查清单_v1.4.md | 2963 | `df9db82dd8de4ef7eba124641006b3408af87aa5db253dbdacbc7027d6d7bd19` | `df9db82dd8de4ef7eba124641006b3408af87aa5db253dbdacbc7027d6d7bd19` | 一致 |
| 03_文件服务接口约定_v1.2.md | 2984 | `35b8a7aef0d004cc1c239b85c34fdfbab197aa420f07974417d468c1f692f53b` | `35b8a7aef0d004cc1c239b85c34fdfbab197aa420f07974417d468c1f692f53b` | 一致 |
| 04_星桥项目_需求与范围_v1.0.pdf | 186886 | `e667d079d17393fd6c3d06a7b9a99affa932515798d9ad3c7e6fad2f9d0615c7` | `e667d079d17393fd6c3d06a7b9a99affa932515798d9ad3c7e6fad2f9d0615c7` | 一致 |
| 05_星桥项目_发布检查清单_2026-09-18.txt | 2483 | `bfd47158f7f72eabb1620620b769fde09a3f63c70451c08d814b35672e13f1a1` | `bfd47158f7f72eabb1620620b769fde09a3f63c70451c08d814b35672e13f1a1` | 一致 |
| 06_星桥项目_故障复盘_2026-09-21.md | 3092 | `6ab30bcc2159c3d5a613480626ada1bd9ebbe770521cb033d9ac4ff607b29527` | `6ab30bcc2159c3d5a613480626ada1bd9ebbe770521cb033d9ac4ff607b29527` | 一致 |
| 07_星桥项目_用户访谈纪要_2026-09-12.txt | 2908 | `6872d1e8ed62ed0925c5a76d82be13021908655e3c6fe7ee6e832c274691338b` | `6872d1e8ed62ed0925c5a76d82be13021908655e3c6fe7ee6e832c274691338b` | 一致 |
| 08_检索技术说明_关键词与语义_v1.0.pdf | 187732 | `6ad61f30a48e2d4a447fdae23ed2fc2409f504814b3155ec1cb4fd1949971368` | `6ad61f30a48e2d4a447fdae23ed2fc2409f504814b3155ec1cb4fd1949971368` | 一致 |
| 09_本地部署故障排查_v1.3.txt | 3017 | `f06706263f499059e1225f5cfb9d491196d7e4501b56fc0aae23605fa6e8003f` | `f06706263f499059e1225f5cfb9d491196d7e4501b56fc0aae23605fa6e8003f` | 一致 |
| 10_文档分类与归档规范_v1.0.pdf | 170109 | `bc91d25e2db7f8c36d8ea0ffc8a18ee6993752d14eb5dcbc221fcc4e7b24b695` | `bc91d25e2db7f8c36d8ea0ffc8a18ee6993752d14eb5dcbc221fcc4e7b24b695` | 一致 |

## 元数据与异常检查

| 检查 | 结果 | HTTP |
|---|---|---|
| list_metadata_and_pagination | 通过 | — |
| empty_file | 通过 | 400 |
| unsupported_type | 通过 | 415 |
| invalid_pdf | 通过 | 415 |
| invalid_filename | 通过 | 400 |
| oversized_file | 通过 | 413 |
| unknown_file | 通过 | 404 |
| unknown_download | 通过 | 404 |
| invalid_pagination | 通过 | 422 |
| missing_multipart_boundary | 通过 | 400 |
| rejected_uploads_do_not_create_records | 通过 | — |
| independent_sqlite_and_storage_hashes | 通过 | — |

- 元数据名称/大小/哈希/UTC 时间/索引状态与上传返回一致；详情返回同一记录。
- 独立 sqlite3 连接核对已提交记录，直接读取持久化原文件计算哈希一致；正常完成后无残留 .part 或 .intent.json。
- 超限、空文件、错误格式、无效 PDF、文件名路径、无效分页、未知文件及缺少 multipart boundary 有明确接口响应；拒绝上传未生成记录。

## 容器与浏览器实测

- 最新成功证据：`m2-docker/20261007T134041Z-485852`。构建/启动退出码 0，命令耗时 90.156 秒；容器校验命令退出码 0，耗时 9.405 秒；脚本总耗时 99.768 秒。
- 校验通过真实 TCP `http://app:8000` 访问主应用。10 份下载 SHA-256 与本报告表中原始哈希相同，12 项附加检查通过，校验内部总耗时 8.442 秒；原始 JSON 见 docs/evidence/m2/container-results.json。
- 浏览器上传、详情和下载：由用户在本次消息明确确认。不是将静态资源返回 200 替代为点击验收；本阶段未另外执行响应式 viewport 截图检查。

## Windows 日志编码修复

- 旧失败证据 `m2-docker/20261007T132049Z-d269f4` 保留：GBK 无法输出 Vite 的 U+2713，嵌套 runner 退出 1，构建子步骤 exit_code=None，不能当作应用构建失败或成功。
- scripts/utf8_logs.py 固定当前 Python 的 stdout/stderr 为 UTF-8，为子进程继承 UTF-8 环境变量；各 runner 的 subprocess 明确按 UTF-8 解码，日志按 UTF-8 写入，不改变系统或执行策略。Dockerfile 在模型下载前同时复制此共享模块。
- 强制初始 PYTHONIOENCODING=gbk/PYTHONUTF8=0，执行修复并启动嵌套 Python，实际输出 ✓ 中文，退出码 0，无 stderr。证据见 docs/evidence/m2/encoding-results.json。该脚本修复于本次在 Windows 本地验证，下一次 M3 构建将包含修复；不伪造此前容器运行已包含此改动。

## 已知边界
- 下载是原始字节；PDF 仅做文件头检查，未实现预览或全文提取。TXT/Markdown 不改变编码，正文索引后续建立。
- 同名文件不覆盖；重复上传目前可能生成多个条目，没有内容去重或幂等键，留到 M5。
- 正式文件落盘后数据库提交不确定时保留字节及意图并明确提示核对。启动对账/隔离恢复及故障注入仍未实现和测试；见 docs/crash-consistency.md。

## Git

M1 基线提交：`2e92b5d`（Complete M1 Docker skeleton and verified vector retrieval）。本次 M2 提交包含实现、日志编码修复及上述实测证据；提交号以 Git 历史为准。
