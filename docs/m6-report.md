# M6 空卷、重建、回归与代码审查报告

状态：Docker 真实 HTTP、内置浏览器桌面/窄屏操作及审查修复已通过。普通 Chrome 的主要流程和约 390px 操作仍等待用户实际核对；用户回复“我会核对并回复”不计通过，暂不宣布最终验收完成。

M4 提交 462599d；M5 提交 35687a6。两阶段报告、来源片段与浏览器截图已随源码保存。M6 本轮修复正文重试并发竞态，补充独立空数据卷验证和便携启动说明；未新增问答、版本管理或 PDF 正文功能。

## 执行与耗时

工作目录为项目根目录。实际启动验证命令：`python scripts/run_m6_docker.py --zip D:\__10_.zip`。该路径仅是本次测试资料位置；程序接受任意 ZIP 路径，正常部署不需要 ZIP 或宿主机 Python。

修复后运行目录 `20261008T041154Z-m6-3abc52dc4a32`；总退出码 0、134.633 秒。完整子命令、退出码和耗时在 [execution-summary.json](evidence/m6/execution-summary.json)。

| 实际步骤 | 退出码 | 耗时（秒） |
| --- | --- | --- |
| 独立 Compose 项目 `up --build -d --wait`，新命名数据卷 | 0 | 93.022 |
| review 专项（真实模型、竞态、模型缺失与修复后重试） | 0 | 14.529（检查内部 13.606） |
| 空卷全流程 prepare | 0 | 7.583（检查内部 6.651） |
| `restart app` / 等待健康 | 0 / 0 | 1.363 / 5.394 |
| 重启后读取快照、下载及检索 | 0 | 1.075 |
| `up --no-build --force-recreate --wait` | 0 | 6.992 |
| 重建后读取快照、下载、归档恢复及检索 | 0 | 1.134 |

证据复制、日志读取和自建测试项目停止步骤全部退出码 0。测试卷保留为 `m6-3abc52dc4a32_platform_data`，主服务原卷未用于空卷实验。基础镜像、依赖和模型使用已有构建缓存；没有把本轮描述为清空所有构建缓存后的重新下载。

最初空卷回归（修复前）退出码 0、124.267 秒；之后 review 发现竞态，专项复现退出码 **1**，内部 5.878 秒，错误为 `Text retry did not invalidate the processing generation`。这次失败保存在 [review-before-failed.json](evidence/m6/review-before-failed.json)，没有改写成通过。修复后才重新运行上述全部回归。

已将同一已验证镜像标记为当前 `knowledge-platform-app`，以 `docker compose up -d --no-build --wait --wait-timeout 180` 启动原服务；退出码 0、7.118 秒。实际健康为 ready，数据库/本地模型 ready、索引 workerRunning=true、concurrency=1；见 main-image-start.json、main-health.log。

## 验收证据

| 验收点 | 实测结果及证据 |
| --- | --- |
| README 无旧数据或宿主机路径依赖 | 独立新卷初始 0 文件、0 分类，页面 HTTP 200，语义结果为空；按同一 Dockerfile/Compose 启动。README 启动只要求 Docker/Compose。04-prepare.json |
| PDF/TXT/Markdown 保存与下载 | 新上传真实 ZIP 的全部 10 份文件，每个下载 SHA-256 与 ZIP 原始字节一致；7 文本 ready、3 PDF 仅名称。04-prepare.json.business.uploads |
| 新上传业务索引 | 新文件 ID→正文→74 片段→512维持久化向量→改写查询→原文来源；独立 SQL 验证片段唯一及每向量 2048 字节。04-prepare.json.business |
| 分类、关键词、归档 | 创建/改名、中文、完整编号、字面百分号/下划线、空结果、分页、分类组合、移动→搜索→归档→搜索→恢复→搜索通过。04-prepare.json.keywords（9 项） |
| 常见错误 | 空文件 400，超限 413，不支持类型/伪 PDF 415，路径文件名 400；空分类/错误参数 422、重复分类 409、未知资源 404、PDF 索引重试 409。04-prepare.json（8 项，另含业务/关键词子检查） |
| 正文失败不破坏下载 | 无效编码 TXT 上传 201，正文 failed，名称搜索命中；正文重试仍明确失败，原始字节 SHA 一致下载。04-prepare.json.keywords.extraction_failure |
| 重启/强制重建 | 11 文件 ID、哈希、分类、两个非空 archivedAt、任务代次/次数、74 向量字节哈希均与前快照完全一致；10 份原资料再次下载 SHA 相等。07-after-restart.json、09-after-recreate.json |
| 重建后归档过滤及恢复 | 两个归档文件排除默认列表；归档区关键词/语义命中。恢复 PDF/Markdown 后下载 SHA 一致，Markdown 再次参与默认语义检索。09-after-recreate.json |
| 任务恢复/原文件未提交崩溃 | M5 已实际退出进程 75/74 验证 processing 重领及孤儿隔离，未冒充正常重启覆盖崩溃；完整证据沿用 evidence/m5/results.json |
| review 修复 | 处理中连续三次索引重试保持代次1/尝试1；正文重试立即变代次2 pending；释放旧推理后，仅代次2片段发布且尝试2，无重复。03-review-after.json |
| 实际模型缺失 | 使用不存在的 MODEL_DIR，健康 degraded/模型 failed；正文 ready、向量 failed，关键词命中、下载 SHA 相等，语义 503 MODEL_UNAVAILABLE。恢复真实模型后手动重试成功并真实检索。03-review-after.json |

五组问题在 M6 新卷中新上传文档上的实际预期来源排名依次为 **1、1、2、1、1**（完整问题、各文件排名/分数、逐查询耗时及来源片段见 04-prepare.json.business.queries；M5 报告亦有片段表）。全部目标在默认阈值 0.45 下可返回。第三组目标排第二、第2/3组强片段较泛，保留这个检索质量限制，不声称所有问题均第一或问答正确。

## 浏览器证据和待测项

M4 内置浏览器关键词/编号/空结果/PDF名称与分类归档流程已验证并提交。M5 内置浏览器实际新上传真实 TXT/Markdown，索引就绪、来源片段、分类移动、归档恢复、刷新及下载通过；1280×900 和 390×844 实测，窄屏 scrollWidth=375 ≤ innerWidth=390。已修复窄屏按钮挤压和片段标题换行，截图在 evidence/m5。

M6 当前修复镜像下，内置浏览器实际点击“重试正文提取”，观察 pending 后回到 failed，错误原因保持清晰；点击“下载原文件”取得真实落盘文件，SHA-256 为 `d5e1679bb098e65c4f1efd9c1db7febb2b90dcbe0df1ae64da614520492247b6`，与 M4 原始3字节测试文件一致。截图/动作记录见 evidence/m6/m6-browser-failure.png、m6-browser-failure-trace.txt。未把该正文失败案例冒充“正文 ready/仅向量失败”的浏览器验证；后者已有真实 HTTP 证据。

仍待普通 Chrome 主要流程和约390px的用户核对结果。Chrome 自动控制连接失败，内置浏览器证据不等同普通 Chrome 通过。未经此次实际执行的环境：另一台全新主机/完全无构建缓存下载。当前没有未修复的已复现业务失败，尚未完成的浏览器核对继续追踪。

代码审查范围、修复依据及已知限制见 [code-review.md](code-review.md)。
