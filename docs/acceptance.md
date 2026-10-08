# 题目要求 → 页面/API → 实际证据

证据分为自动化 Docker 真实 HTTP、Agent 内置浏览器操作、用户手动验证；彼此不替代。通过只指已执行项目，不推断未测浏览器或未知环境。更新阶段：P0。

| 题目硬条件 | 页面入口 / API | 实际证据与状态 | 已知限制/待验证 |
| --- | --- | --- | --- |
| Docker 部署 | README；Dockerfile、compose.yaml；GET /api/v1/health | 自动化通过：M6 独立空卷启动、重启及重建，evidence/m6/execution-summary.json | 首次依赖安装/模型下载无缓存构建待补 |
| PDF/TXT/Markdown 上传、状态与下载 | 上传入口、列表/详情下载；POST /documents、GET /documents/{id}/download | 自动化通过：M6 全部10份 SHA 一致；M2 用户手动确认上传/详情/下载。evidence/m6/04-prepare.json | PDF 正文/预览尚不支持 |
| 文件名称、分类、大小、时间、详情 | 文件主区、文件详情；GET /documents、GET /documents/{id} | 自动化及内置浏览器通过：M2/M5 报告、evidence/m5/browser-desktop.png | 页面首屏/侧栏/抽屉优化待完成 |
| 分类创建、修改、归属、筛选、刷新持久化 | 分类管理、分类筛选、详情移动；POST/PATCH /categories、PATCH /documents/{id}/category | 自动化通过：本轮 P0 同一次链路创建→改名→移动→列表和两种搜索过滤→独立HTTP刷新读取。evidence/p0/results.json | 新布局的普通浏览器链路待核对 |
| 文件名、TXT/MD正文关键词及分类组合 | 关键词搜索；GET /search/keyword | 自动化通过：中文、完整编号、字面字符、摘要/空结果；M4/M6 证据及本轮 P0 | PDF 仅名称；文本编码失败不参与正文搜索 |
| 真实向量生成、存储、自然语言检索及来源 | 自然语言搜索；GET /search/semantic | 自动化通过：M5/M6 新上传7文本→74片段→512维BLOB→5组改写排名；内置浏览器新TXT/MD通过 | 设备查询夹杂发布资料：用户手动发现且本轮只读HTTP复现；检索质量待优化 |
| 索引状态、失败可下载、重试 | 列表状态、详情错误/重试；POST /documents/{id}/index/retry、text/retry | 自动化通过：推理失败、真实模型缺失、进程退出后重领、代次/唯一片段；M5/M6；内置浏览器正文失败重试/下载 | 普通浏览器“正文ready/向量failed”未单独宣称通过 |
| 归档排除默认列表/检索、恢复/下载 | 文件库/归档区、归档/恢复；POST /documents/{id}/archive、restore | 自动化通过：本轮 P0 同一文件默认列表/关键词/语义全部排除，归档区可找，恢复后重新命中且 SHA 一致。evidence/p0/results.json | 用户手动 M3认可，但没有自动补造逐动作记录 |
| 持久化文件、分类、归档及检索 | /data 命名卷 | 自动化通过：M6 11文件、2非空归档状态、74向量字节哈希重启/强制重建完全一致 | 不覆盖清空数据卷或更改Compose项目名后的数据迁移 |
| 异常反馈和空结果 | 上传错误、详情错误、空结果页 | 自动化通过：400/413/415/422/404/409，正文失败原文件保存；M6。内置浏览器空结果/失败重试通过 | 新UI异常展示复测待完成 |
| 清晰入口、普通屏幕可操作 | 页面布局 | 内置浏览器旧版1280×900、390×844操作通过；用户手动记录见 user-validation.md | 新布局及普通Chrome逐项状态待验证；不把“我会核对”当通过 |
| 5组真实资料语义示例、源码来源、设计与限制 | docs/m5-report.md、model-spec.json、README | 已交付实际排名/来源及组件链接，M5；M6复测1/1/2/1/1 | 优化后结果与最终交付汇总待更新 |

API 路径均以 `/api/v1` 为前缀。本轮 P0 命令 `python scripts/run_acceptance_docker.py` 创建独立新容器/卷，只监听127.0.0.1:18080，测试完仅移除自建容器。真实TCP检查4项通过，检查内部0.878秒；每次请求响应与下载哈希在 evidence/p0/results.json，退出码/步骤耗时在 execution-summary.json。它没有向演示8000端口创建测试分类或文件。

本轮后续缺口与计划见 optimization-plan.md；普通浏览器只依据实际结果更新。
