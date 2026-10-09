# 题目要求 → 页面/API → 实际证据

当前交付状态（2026-10-09）：代码与交付文档已完成、GitHub公开源码已发布；平台SHA锁定、原始日志上传及材料回执尚未完成，见[remaining-acceptance.md](remaining-acceptance.md)。本次只定稿文档，未重新执行业务回归。下表使用已有最新实测证据；自动化Docker真实HTTP、Agent浏览器、用户手动验证彼此不替代，不推断未测环境。表后历史追加记录保留当时措辞。

| 题目硬条件 | 页面入口 / API | 实际证据与状态 | 已知限制/待验证 |
| --- | --- | --- | --- |
| Docker 部署 | [README](../README.md)；Dockerfile、compose.yaml；GET /api/v1/health | 自动化通过：Git源码无缓存安装/模型下载、独立空卷、重启/重建，见[完整回归](final-candidate-review.md)；检索调整后另有新源码构建/空卷HTTP，见[最新回归](retrieval-round.md) | 最新检索构建使用依赖缓存，不算另一次首次安装；Windows Docker Desktop Linux容器已实测，其他宿主系统未专项验证 |
| PDF/TXT/Markdown 上传、状态与下载 | 上传入口、列表/详情下载；POST /documents、GET /documents/{id}/download | 自动化通过：M6 全部10份 SHA 一致；M2 用户手动确认上传/详情/下载。evidence/m6/04-prepare.json | PDF正文/OCR不支持；预览接口SHA已验证，阅读器显示的专项人工明细未提供 |
| 文件名称、分类、大小、时间、详情 | 文件主区、文件详情；GET /documents、GET /documents/{id} | 自动化及内置浏览器通过：M2/M5 报告、evidence/m5/browser-desktop.png | 新版搜索/上传/列表在首屏，侧栏/抽屉/390px卡片已由Agent内置浏览器验证，见ui-optimization.md |
| 分类创建、修改、归属、筛选、刷新持久化 | 分类管理、分类筛选、详情移动；POST/PATCH /categories、PATCH /documents/{id}/category、PATCH /documents/batch/category | 自动化通过：创建→改名→移动→列表/两种搜索过滤→独立HTTP刷新读取，最新[P0结果](evidence/retrieval-round/p0/results.json)；批量整理见[batch-organization.md](batch-organization.md) | 用户手动普通Chrome批量移动/数量/刷新及两种搜索过滤通过；后续用户汇总确认完成，未附专项动作/尺寸 |
| 文件名、TXT/MD正文关键词及分类组合 | 关键词搜索；GET /search/keyword | 自动化通过：中文、完整编号、字面字符、摘要/空结果；M4/M6 证据及本轮 P0 | 普通Chrome关键词分类过滤用户手动通过；PDF仅名称，文本编码失败不参与正文搜索 |
| 真实向量生成、存储、自然语言检索及来源 | 自然语言搜索；GET /search/semantic | 自动化通过：新上传TXT/MD→分片→512维持久化向量→HTTP片段；最新14份资料/98片段、39题（31正向全命中、8无关为空），原五问排名1/1/2/1/1，见[retrieval-round.md](retrieval-round.md) | 默认窗口0.08，绝对门槛0.45；按标签无关返回64→40，仍有高分误返回/来源泛化，不能标为全部质量通过。普通Chrome语义分类过滤用户手动通过 |
| 索引状态、失败可下载、重试 | 列表状态、详情错误/重试；POST /documents/{id}/index/retry、text/retry | 自动化通过：推理失败、真实模型缺失、进程退出后重领、代次/唯一片段；M5/M6；内置浏览器正文失败重试/下载 | 普通浏览器“正文ready/向量failed”未单独宣称通过 |
| 归档排除默认列表/检索、恢复/下载 | 文件库/归档区、归档/恢复；POST /documents/{id}/archive、restore | 自动化通过：最新[P0结果](evidence/retrieval-round/p0/results.json)，默认列表/关键词/语义均排除，归档区可找，恢复重现且下载SHA一致 | 用户已汇总确认人工完成，未提供本链路逐动作明细，不追加人工细节 |
| 持久化文件、分类、归档及检索 | /data 命名卷 | 自动化通过：M6 11文件、2非空归档状态、74向量字节哈希重启/强制重建完全一致 | 不覆盖清空数据卷或更改Compose项目名后的数据迁移 |
| 异常反馈和空结果 | 上传错误、详情错误、空结果页 | 自动化通过：400/413/415/422/404/409，正文失败原文件保存；M6。内置浏览器空结果/失败重试通过 | 新UI已有内置浏览器空结果/错误展示证据，后续用户汇总确认完成，未附错误反馈专项明细 |
| 清晰入口、普通屏幕可操作 | 页面布局 | 内置浏览器新版1280×900、390×844分类/搜索/详情/归档操作通过，见ui-optimization.md；用户手动记录见 user-validation.md | 普通Chrome批量整理入口/操作通过；后续用户汇总确认完成；尺寸/键盘专项明细未提供 |
| 5组真实资料语义示例、源码来源、设计与限制 | [交付导航](submission.md)、model-spec.json、README | 五问真实HTTP排名1/1/2/1/1及来源见[最新检索报告](retrieval-round.md)；架构/组件来源/本人范围见[delivery.md](delivery.md)，真实公开仓库已发布 | 代码与文档已完成；平台SHA锁定、原始日志上传/回执未完成，见[remaining-acceptance.md](remaining-acceptance.md) |

## 历史阶段追加记录（保留当时状态）

以下记录来自先前阶段，“本轮”“候选”“待核对”等均对应当时，不用于覆盖上方最终状态；历史报告和原始证据文件未改写。

API 路径均以 `/api/v1` 为前缀。本轮 P0 命令 `python scripts/run_acceptance_docker.py` 创建独立新容器/卷，只监听127.0.0.1:18080，测试完仅移除自建容器。真实TCP检查4项通过，检查内部0.878秒；每次请求响应与下载哈希在 evidence/p0/results.json，退出码/步骤耗时在 execution-summary.json。它没有向演示8000端口创建测试分类或文件。

本轮后续缺口与计划见 optimization-plan.md；普通浏览器只依据实际结果更新。

新增扁平分类批量整理已完成：创建后添加文件、分类页选择弹窗、列表批量移动，实际验证多文件刷新、数量、两种搜索过滤、部分失败恢复重试和窄屏提交。最终镜像独立空卷批量6项+既有分类归档4项通过；当前演示26文件/9分类及下载SHA保留。证据见 [batch-organization.md](batch-organization.md)，上述数字属于自动化与Agent内置浏览器结果。用户另行明确普通Chrome批量分类通过：添加入口、多选移动、数量更新、刷新保留及两种搜索过滤；人工原话见user-validation.md。

**历史人工失败：旧侧栏改名控件不可达。** 用户报告旧侧栏改名控件越过视口、无法滚动操作。已改为弹窗和独立列表滚动并部署；本次独立 Docker 分类/搜索/归档链路4项、Agent内置浏览器1280×480及390×480/300改名和刷新均通过，原26文件/8分类及下载SHA保留。普通Chrome批量整理已另行通过，后续用户已汇总确认完成；改名、低高度及390px专项动作明细未提供，不能将上述自动化替代人工状态；完整证据及截图见 [category-dialog-fix.md](category-dialog-fix.md)。

最终检索策略下P0独立空卷再次验证4项通过，内部0.476秒、退出0，见evidence/p0-final。用户已确认内置浏览器TXT/MD上传及设备来源，并新增普通Chrome批量分类通过；未明确涵盖的专项在manual-check.md，全部剩余事项在remaining-acceptance.md。


### 候选阶段收尾结果（历史）

用户已另行汇总确认“我已验证完成”，原话与证据来源见[user-validation.md](user-validation.md)，不补造专项动作/尺寸。本轮从候选Git源码无缓存构建、独立空卷部署和完整回归均通过，运行代码无新增修改，演示26文件/9分类及26份下载SHA保留。早期待核对描述对应当时阶段；最新实测、故障恢复、限制及原始日志见[final-candidate-review.md](final-candidate-review.md)，剩余交付条件见[remaining-acceptance.md](remaining-acceptance.md)。按要求暂不锁定最终SHA。

后续独立语义修改73cb634：默认文件窗口0.12→0.08，绝对门槛/来源排序保留。39题预声明对照与新镜像真实HTTP，31目标全命中、8无关为空，按标签无关返回64→40；仍有高分误返回/泛化片段，不标为全部质量通过。已补跑关键词/语义当前分类、归档恢复及下载SHA的4项P0，既有检索/同名回归通过；新镜像部署后26文件/9分类完整保留。详见[retrieval-round.md](retrieval-round.md)。此为自动化证据，无新增人工浏览器确认。
