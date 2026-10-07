# M3 验证报告

状态：M3 已完成。分类和归档的本地、容器真实 HTTP、浏览器操作及刷新已验证；恢复后浏览器保存文件的字节和 SHA-256 与 ZIP 原文件一致。M2 报告及 Windows UTF-8 日志修复已提交 `2f14cf5`。

## 验证清单与改动

- 创建/修改扁平分类，空白、重名、超长和非法名称有明确反馈。
- 在详情移动文件，支持回到未分类；列表、详情与分类筛选一致。
- 分类与归档状态入 SQLite，重新读取仍保留；筛选和归档视图进入 URL，整页刷新恢复条件。
- 默认列表及分类列表排除归档文件；归档区支持分类筛选、详情与下载。
- 恢复后回到原分类，可下载且 SHA-256 与原资料一致。
- 启动以事务升级 M2 业务表，保留已有记录和原文件。检索功能、上传任务恢复、去重及故障注入没有进入本阶段。

新增 categories 表与 documents.category_id/archived_at，schema user_version=1。新增分类 CRUD 中的创建/改名，以及文件分类调整、归档和恢复接口；API 清单见 platform/docs/m3-api.md。保持一个 app 服务、一个 Web worker、原具名数据卷。

## 本地实际执行

目录为工作区根目录。先用 SQLite backup 复制 `work/m2-data/db/platform.sqlite3` 到 `work/m3-upgrade-test/db/` 并复制对应 uploads 原文件；没有修改源 M2 测试库。执行：

```powershell
& '.\work\m1-venv\Scripts\python.exe' 'outputs\platform\scripts\verify_m3.py' --zip 'D:\__10_.zip' --data-dir 'work\m3-upgrade-test' --report 'outputs\m3-local-results.json'
```

退出码 0，耗时 21.372 秒，14 项检查通过。传输为 in-process ASGI TestClient，不是容器 HTTP 或浏览器操作证据：

- 原有 10 份 ZIP 文件均能下载，字节及 SHA-256 与原资料一致；升级前版本 0、升级后版本 1，10 个 ID/哈希全部保留。
- 创建、规范化去空白、改名、冲突反馈、文件移动、分类筛选、回到未分类通过；失败目标没有改变既有归属。
- PDF 归档后默认列表、显式未归档列表及所在分类列表均排除该文件；归档区及分类组合筛选能找到。
- 独立 SQLite 连接读到同一分类外键与归档时间；重新 GET 保留状态，分类计数正确。
- 归档时仍可下载原字节；重复归档不改时间，重复恢复成功。
- 恢复后默认列表及分类列表可找到，归档区不再返回；文件名、大小、上传时间、哈希及索引状态未改变。

恢复下载实测文件 `04_星桥项目_需求与范围_v1.0.pdf`，HTTP 200：

| 比较项 | SHA-256 |
| --- | --- |
| ZIP 原文件 | `e667d079d17393fd6c3d06a7b9a99affa932515798d9ad3c7e6fad2f9d0615c7` |
| 恢复后下载 | `e667d079d17393fd6c3d06a7b9a99affa932515798d9ad3c7e6fad2f9d0615c7` |

另以独立 Python/SQLAlchemy 检查空库创建、启用外键、第二次打开已升级数据库：退出码 0，耗时 0.060 秒，10 份记录的分类/归档/哈希及两项分类名称不变。证据 m3-schema-results.json。仅为数据库再次打开，不声称容器重建或任务重启恢复通过。

前端 TypeScript/Vite 构建退出码 0，28 模块、Vite 1.50 秒。git diff --check 退出码 0。

首次本地 ASGI 运行在 Windows asyncio 创建回环 socketpair 时挂起；诊断调用栈确认尚未进入应用启动，已中断该运行。取得本轮网络权限后以上命令实际通过，不将中断运行标为成功，也未为此修改应用事件循环或安全设置。

## 容器实际执行

用户在普通 PowerShell 执行以下命令；工具读取保存日志并核对。scripts/run_m3_docker.py 一轮只构建/启动一次，随后验证容器通过真实 HTTP 访问主应用并独立读共享卷数据库。各步记录命令、退出码及日志。ZIP 始终使用 `D:\__10_.zip`。

```powershell
& 'C:\Users\lenovo\AppData\Local\Programs\Python\Python313\python.exe' 'C:\Users\lenovo\Documents\Codex\2026-10-07\48-web-docker-1-2-pdf\outputs\platform\scripts\run_m3_docker.py' --zip 'D:\__10_.zip'
```

本轮证据 `m3-docker/20261007T143120Z-c8948b`：

| 步骤 | 退出码 | 命令耗时 |
| --- | ---: | ---: |
| 构建及启动 | 0 | 38.345 秒 |
| 容器分类/归档/下载验证 | 0 | 7.046 秒 |
| 应用日志读取 | 0 | 0.163 秒 |
| 整轮脚本 | 0 | 45.555 秒 |

容器通过真实 TCP `http://app:8000` 完成 14 项检查，校验脚本内部耗时 6.287 秒，failure=null；10/10 测试资料下载字节/哈希一致，PDF 恢复后 HTTP 200 且哈希同上。health 为 M3 ready，数据库和本地模型 ready，启动 4.984 秒。日志中的 409、422、404 是重名、非法输入和不存在目标的预期异常用例，不是校验失败。新构建包含 UTF-8 日志修复，未再出现 GBK 编码异常。

容器脚本没有启动前快照，因此其中 schema 检查不能单独证明升级前后的全部 ID 不变。额外逐一比较 M2 容器报告里的 10 个文件 ID/哈希与 M3 数据库快照：10/10 保留，证据 existing-container-data.json；本地副本的启动前/后完整 schema 对比仍见 local-results.json。

## 浏览器实际验证

工具在 Codex 内置浏览器访问 `http://127.0.0.1:8000/`，通过真实页面控件完成：

- 创建 `M3浏览器验收-分类`，改名 `M3浏览器验收-已改名`；空名称与重名均显示明确错误。
- 将 04 PDF 从脚本测试分类移到改名后的分类，按分类筛选。整页刷新后 URL 分类参数、分类名称及该文件仍保留。
- 归档 PDF 后刷新，所在分类未归档计数为 0；切换全部分类，默认文件库总数从 11 变为 10，PDF 不在列表中。
- 切换归档区并按该分类筛选、整页刷新，URL 中 archived=true 与 category 均保留，PDF 仍可找到。
- 点击恢复，归档区不再返回该 PDF；回到文件库并整页刷新，原分类下再次显示 PDF。
- 点击下载，页面显示已接收。下载事件 API 等待 15 秒超时，但实际文件已保存到 `C:\Users\lenovo\Downloads\04_星桥项目_需求与范围_v1.0.pdf`，修改时间 2026-10-07 22:42:39（本机时区）；独立读取 186886 字节，与 ZIP 原字节完全一致，SHA-256 为上表值。事件 API 超时没有标为通过。

浏览器证据 browser-results.json、m3-browser-archive.png、m3-browser-restored.png 已保存到输出目录，并复制到 docs/evidence/m3。截图显示归档区与恢复后的分类文件库。未以截图声称移动端布局或容器重建已验证。

## 已知限制

不提供分类删除、目录树和权限。关键词/语义检索在 M4；当前 textStatus/vectorStatus 仍为 not_started，因此尚不能声称恢复后重新检索通过。任务恢复、去重、故障注入在 M5。M2 到 M3 构建重新创建容器后原有 10 份测试文件已核对保留；M3 新增的分类/归档状态仅实测页面刷新与独立磁盘读取，没有额外执行容器重新创建。验收脚本与浏览器操作留下三个测试分类，04 PDF 现归属浏览器验收分类且未归档；不会删除原文件。移动端布局未在本阶段实测。
