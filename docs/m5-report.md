# M5 业务索引与语义检索实测报告

状态：本地真实 TCP HTTP 及 Docker 实测通过，内置浏览器新上传/语义来源/过滤已通过；普通 Chrome 用户核对中，窄屏样式修复已复测通过。未宣布最终交付。

M4 已提交 462599d。方案实现与状态规则见 [m5-api.md](m5-api.md)。README 已改为项目根目录 Docker 启动，无需本机 Python/Node、固定路径、ZIP 或已有数据；历史环境命令迁入 development-history.md。

## 实际命令、退出码与耗时

本地：python scripts/verify_m5.py --zip 测试ZIP路径 --data-dir 独立临时目录 --report 输出路径；退出码 0，307.4 秒，11 项检查。是真实子进程 Uvicorn TCP HTTP，非 ASGI/M1 实验。

Docker：python scripts/run_m5_docker.py --zip D:\__10_.zip。20261008T034005Z-8fc0af 日志：构建 0/90.458 秒；启动 0/7.206 秒；验证 0/37.422 秒（内部 36.389 秒、10 项检查）；复制证据、读取日志、移除自建验证容器均 0，总 135.764 秒。日志在 docs/evidence/m5。

## 新上传数据和实测查询

主应用新上传 10 份 ZIP 资料，使用本轮新文件 ID 和独立分类约束查询，不复用 M1 实验向量。7 份文本共 74 个片段，3 份 PDF 仅名称。全部原/下载 SHA-256 相等。独立 SQLite 读取确认每片段 2048 字节（512×float32），文件+ordinal 唯一，重建索引后没有重复片段。

| 改写问题 | 预期来源（实际命中） | 实际排名/分数 | 返回来源片段节选 |
| --- | --- | --- | --- |
| 交给同事审阅修改之前，应该怎样自查并描述测试结果？ | 01_代码提交规范_v2.1.md | 1 / 0.643228 | 若某项检查未执行，应写出具体原因和未验证范围。不能把“代码看起来没有问题”填写成测试通过。 |
| 网络断了又提交同一份上传请求，服务怎样防止保存两次？ | 03_文件服务接口约定_v1.2.md | 1 / 0.658537 | 成功保存后返回 201，响应示例： |
| 上线刚启动，新版本要验证哪些用户操作才能放心交付？ | 02_发布检查清单_v1.4.md | 2 / 0.587539 | 本项目发布后至少观察十分钟。若新版本导致持续的服务端错误、上传文件无法下载，或索引任务完全停止消费，应暂停继续发布。排查配置问题时也要记录影响范围，不能反复重启来掩盖故障。 |
| 文档上传成功却查不到正文，数据换了嵌套结构，怎么补救而不用重传？ | 06_星桥项目_故障复盘_2026-09-21.md | 1 / 0.736753 | 重试依据 documentId 和内容版本去重。写入新分片前先核对当前索引版本，避免同一文档在搜索结果里重复出现。已归档文件即使重新生成索引，也不能进入默认搜索结果。 |
| 重建运行环境后以前的资料丢了，该怎样排查挂载和保住原有数据？ | 09_本地部署故障排查_v1.3.txt | 1 / 0.685913 | 先核对数据库和上传目录是否挂载了具名卷或明确的宿主机目录。没有挂载的容器可写层不能承担持久化资料存储。还要检查是否更改了 Compose 项目名称，导致应用连接了另一组新数据卷。 |

排名验证用 min_score=0 查看完整文档次序；目标分数均超过页面默认 0.45。完整来源、代次、各问题耗时和全部排名在 results.json。排名 Top3 5/5 是这组资料的实测，不是任意问题准确率保证；第 2、3 个问题的最强片段偏通用上传/发布上下文，页面展示的第二片段及原文仍需人工判断，不声称问答正确。

## 故障与恢复证据

- live_category_archive_restore_filters_and_download：通过。
- independent_sqlite_persisted_512d_unique_chunks：通过。
- reindex_replaces_chunks_without_duplicates：通过。
- actual_inference_failure_text_search_and_download_still_work：通过。
- explicit_retry_after_failure_real_model_ready：通过。
- real_worker_process_crash_with_durable_processing_claim：通过。
- restart_recovers_claim_no_duplicate_chunks_real_query：通过。
- repeated_processing_retry_idempotent_one_job_one_generation：通过。
- real_crash_after_formal_file_before_sql_commit：通过。
- restart_quarantines_uncommitted_original_and_intent_without_data_loss：通过。

故障注入只在隔离验证进程中：实际向量 encode 抛异常，正文 ready/向量 failed，正文关键词命中且 SHA 一致下载；正常模型重启后失败状态保留，手动重试 ready并真实语义命中。实际进程退出 75 后 SQLite processing 与无片段已确认，重启领取该任务（attempts=2），真实模型生成/查询/下载通过，片段不重复。处理中连续三次重试仅一任务/一代次/一次尝试。实际正式文件 fsync 后进程退出 74，数据库无记录；重启将文件与意图隔离，原始字节完整保留。

## 浏览器与继续追踪

内置浏览器 390×844：实际选择并上传重新命名的真实 TXT/Markdown，保存 2 个文件，看到等待索引再变为可语义检索；两者详情各 11 个片段。创建 M5浏览器新资料分类并移动两文件；改写“运行环境重新建立后旧资料不见了…”返回新 TXT 第一位及两段原文（0.669/0.662）。归档后默认结果排除该 TXT，归档区返回；恢复、刷新后分类/问题和 TXT 来源仍存在。浏览器下载落盘 TXT 的 SHA 为 f06706263f499059e1225f5cfb9d491196d7e4501b56fc0aae23605fa6e8003f，与真实 ZIP 相同。

窄屏发现刷新按钮文字挤压及片段标题单行问题，已修正样式并构建成功，已启动复测通过（1280×900 和 390×844，scrollWidth=375 ≤ innerWidth=390），截图及操作记录在 docs/evidence/m5。普通 Chrome 控制通道不可用，用户正在核对；不将内置浏览器等同于普通 Chrome 实测。M6 尚需独立空数据卷部署、非空归档状态容器重建、完整错误与操作回归、代码 review。

补充：样式修复构建退出码 0（单独构建耗时未记录）；启动退出码 0、7.545 秒；实际视觉检查确认刷新按钮不再挤压、片段标题可换行。浏览器下载事件取得真实落盘路径后再次核对 SHA；初次查询下载目录时尚未观察到文件，没有将该次检查记为通过。

M6 后续：独立空卷、非空归档持久化、容器重建和 review 修复已完成，详见 m6-report.md；普通 Chrome 仍待实际核对。
