# 候选源码最终审查与完整回归

本轮输入为候选Git提交`2e6f81fd4ba242073a0d1f57e8c77d0d1171ba06`（运行代码对应`f7496a4`）。从`git archive`导出，目录不含.env、已有数据、宿主模型或frontend/dist，再使用导出源码的Dockerfile/Compose构建。这是可追溯的测试输入，不是最终SHA锁定；按用户要求暂不锁定、不打发布标签、不上传平台原始日志。

## 实际结论

候选源码无缓存构建、新空卷部署、真实HTTP完整回归、重启与强制重建通过；补充批量整理、检索质量及完整M5故障流程也通过。所有编排命令退出0，9份检查报告均无非预期失败。本轮没有修改业务实现或依赖，未发现需修复的阻塞问题。不是新增普通Chrome自动化记录；用户本次汇总确认“我已验证完成”，与下面Agent执行证据分开记录。

演示8000服务保留：全部测试前后26文件、9分类、完整元数据及26份下载SHA一致。测试写入仅使用四个新卷；结束已移除自建测试容器/网络，保留测试卷及报告，没有执行演示卷清空/重建。

## 审查范围与结论

| 范围 | 实际检查 |
| --- | --- |
| 上传限制与路径 | 检查总请求流限制、单文件20MiB、一次一文件、空/格式/文件名限制；随机存储键、路径resolve、下载字节大小/SHA及nosniff；正式落盘与SQL提交分开，意图fsync、崩溃隔离保留原字节 |
| 状态与恢复 | 原文件、正文、向量状态独立；提交文件与索引任务同事务，单任务消费者/推理锁/目录锁；generation阻止旧结果发布，事务替换片段；失败仍可下载，正文ready仍可关键词 |
| 分类与归档 | 批量静态路由、UUID/1–100项校验、去重、BEGIN IMMEDIATE、目标验证、逐缺失文件反馈、SQL回滚及幂等重试；不改字节/归档/索引。两种搜索实时读取当前分类/归档 |
| 页面与错误 | React文本渲染来源、未将TXT/MD作为HTML执行；列表/详情请求代次，预览Blob回收；选择弹窗AbortController、跨页选择、成功移除/失败保留、未知提交结果提示、低高度操作区 |
| 部署与源码 | 24个运行源码/配置与Git导出按LF字节一致；镜像运行用户appuser、Uvicorn workers=1，应用容器只挂载新命名卷/data，无宿主代码/模型/既有数据库绑定；默认空库 |
| 密钥与依赖 | 208个已跟踪文本文件的密钥模式扫描0命中（不等同全面安全审计）；.env/模型/数据不提交。冷构建实际npm ci提示0漏洞，TypeScript/Vite通过；Python包与真实模型运行通过 |

只读审查清单与源码哈希见[evidence/final-candidate/static-review.json](evidence/final-candidate/static-review.json)。没有增加问答、版本、权限、目录树或PDF正文。ZIP中的接口示例/流程规范属于被检索资料，不能将其中的Idempotency-Key等示例自动视为平台的新实现要求。

## 本轮执行与耗时

| 阶段 | 真实结果 | 证据 |
| --- | --- | --- |
| Git导出与冷构建 | archive退出0；docker compose build --no-cache退出0，441.864秒；npm ci 19.8秒、前端build层2.5秒、Python安装层138.9秒、模型download_seconds=150.085（权重95,827,648字节） | cold-regression/00-build.log、execution-summary.json |
| 新空卷启动 | compose up --no-build -d --wait退出0，6.394秒；0文件/0分类，页面200、语义空结果、数据库读写通过 | cold-regression/01-fresh-build-start.log、04-prepare.json |
| 运行审查专项 | 正文重试隔离迟到generation、真实模型缺失degraded/关键词下载/503、还原模型重试3项，14.412秒 | cold-regression/03-review-after.json |
| 完整HTTP准备 | 11项顶层+3项业务+9项关键词检查，6.759秒；新上传10份ZIP的字节/SHA、7文本生成74片段；中文/编号/分类/空结果、错误400/413/415/422/404/409、3PDF预览原SHA | cold-regression/04-prepare.json |
| 重启与重建 | restart+健康等待退出0；强制重建7.180秒退出0。重启后2项0.136秒，重建后3项0.180秒；11记录、分类、2份非空归档、任务、74向量哈希完全一致；恢复后可检索/下载 | cold-regression/07-after-restart.json、09-after-recreate.json |
| 分类归档全链路 | 新空卷4项，0.682秒：创建/改名/移动/两种搜索/归档排除/恢复/SHA | supplement/p0.json |
| 批量整理与SQL故障 | 批量6项2.300秒，SQL回滚及重试等3项0.089秒；同名ID、部分缺失、重复提交、计数、刷新、两种搜索、归档状态、下载SHA | supplement/batch.json、batch-rollback-http.json |
| 检索质量 | 13组正向问题+3组无关问题+分类/归档/同名，4项汇总8.411秒；默认策略五问排名1/1/2/1/1，同义五问1/1/1/1/2 | supplement/quality.json |
| 完整M5流程与故障 | 11项46.289秒：新上传/512维持久化/重建索引、新进程重载、推理失败可下载、重试、实际进程崩溃/任务恢复、重复重试、正式落盘未提交隔离保留 | supplement/m5.json及对应进程日志 |
| 演示资料保留 | 全部测试后再次只读查询/下载，26文件/9分类及26SHA与开始完全一致 | demo-before.json、demo-after-all.json、validation-summary.json |

冷构建主流程总491.285秒，补充流程总75.729秒。这些是实测阶段耗时，不含人工审查/整理时间。--no-cache确实重做RUN安装与模型下载，但基础镜像和WORKDIR元数据本机已有，不宣称“空Docker引擎首次拉取”。本轮模型下载比历史28秒慢，仍成功；未掩盖网络耗时。

所有真实命令、退出码和分步骤耗时在[cold-regression/execution-summary.json](evidence/final-candidate/cold-regression/execution-summary.json)及[supplement/execution-summary.json](evidence/final-candidate/supplement/execution-summary.json)。源目录/测试ZIP的本机路径只是日志事实，README启动不依赖它们。主执行入口为导出源码中的`python scripts/run_m6_docker.py --source-dir <导出目录> --source-sha <候选提交> --zip <测试ZIP> --no-cache`；补充使用同一独立镜像执行verify_acceptance、verify_batch_organization、verify_retrieval_quality和verify_m5。

特别说明：复用verify_batch_after_browser.py中的SQL故障断言时，本次夹具通过HTTP准备，没有新增浏览器操作。原post-browser.json保留原脚本标签；batch-rollback-http.json明确本次来源，不能据旧标签记为浏览器通过。

## 五组本轮真实查询

以下结果来自候选镜像的新上传资料和新向量。使用页面默认阈值0.45、窗口0.12、返回上限5；统一资料分类过滤。展示返回的最多两段，保留原始序号，没有替换片段或硬编码目标。

| 自然语言问题 | 目标文件 | 实际排名 / 分数 | 实际返回来源节选 |
| --- | --- | --- | --- |
| 交给同事审阅修改之前，应该怎样自查并描述测试结果？ | 01_代码提交规范_v2.1.md | 1 / 0.643228 | 片段 #7：若某项检查未执行，应写出具体原因和未验证范围。不能把“代码看起来没有问题”填写成测试通过。；片段 #5：依次完成格式检查、静态检查、受影响模块的自动化测试和本地构建。涉及上传、权限、索引或数据库时，至少覆盖一个成功案例和一个失败案例。不要只证明按钮能点击，要确认接口返回值与数据库最终状态一致。 |
| 网络断了又提交同一份上传请求，服务怎样防止保存两次？ | 03_文件服务接口约定_v1.2.md | 1 / 0.658537 | 片段 #6：成功保存后返回 201，响应示例：；片段 #5：客户端为一次上传生成 Idempotency-Key。服务端在同一用户范围内记住该键与上传请求摘要：相同键、相同内容返回同一文档；相同键、不同内容返回 409，提示生成新请求。网络失败后重试应复用原键，主动再上传一个新版本则使用新… |
| 上线刚启动，新版本要验证哪些用户操作才能放心交付？ | 02_发布检查清单_v1.4.md | 2 / 0.587539 | 片段 #8：本项目发布后至少观察十分钟。若新版本导致持续的服务端错误、上传文件无法下载，或索引任务完全停止消费，应暂停继续发布。排查配置问题时也要记录影响范围，不能反复重启来掩盖故障。；片段 #7：测试材料需要明确标为验证用途，不使用真实用户材料做删除或覆盖测试。验证结束后按记录清理测试数据。 |
| 文档上传成功却查不到正文，数据换了嵌套结构，怎么补救而不用重传？ | 06_星桥项目_故障复盘_2026-09-21.md | 1 / 0.736753 | 片段 #6：重试依据 documentId 和内容版本去重。写入新分片前先核对当前索引版本，避免同一文档在搜索结果里重复出现。已归档文件即使重新生成索引，也不能进入默认搜索结果。；片段 #9：对用户的说明应准确：文件已经保存，索引处理失败，正在恢复检索。不要让用户为了恢复搜索而反复上传同一份文件。 |
| 重建运行环境后以前的资料丢了，该怎样排查挂载和保住原有数据？ | 09_本地部署故障排查_v1.3.txt | 1 / 0.685913 | 片段 #6：先核对数据库和上传目录是否挂载了具名卷或明确的宿主机目录。没有挂载的容器可写层不能承担持久化资料存储。还要检查是否更改了 Compose 项目名称，导致应用连接了另一组新数据卷。；片段 #11：完成一次上传和下载，在正常保留数据卷的前提下重新创建应用容器，再核对原有文件、分类与检索结果。记录验证方式。仅提供一张启动成功截图，不能证明数据可以持久保存。 |

每组before/after/expanded全排名、来源、分类、上传时间与耗时见[supplement/quality.json](evidence/final-candidate/supplement/quality.json)。目标文件排名通过不代表每一段都是最佳解释：接口约定首段是通用201响应；发布检查首段是上线观察，未直接枚举完整操作。仍需用户结合原文判断，不作为知识问答答案。

## 实际故障、恢复与历史修复

本轮应用回归非预期失败为0，运行代码修复为0。证据提交前Git格式检查曾退出2：Windows生成的部分JSON使用CRLF，在未规范化入库时被识别为尾部空白。已仅将证据JSON副本转为LF，逐文件验证JSON值完全不变，原始日志与报告在outputs中保留；修复记录见[evidence-format-check.json](evidence/final-candidate/evidence-format-check.json)。以下是实际执行的故障验证，故意失败不计为整套测试失败：

| 故障/错误 | 实际响应与恢复 | 证据 |
| --- | --- | --- |
| 真实模型推理抛异常 | text ready/vector failed；关键词和下载SHA通过；正常模型进程重新加载后显式重试ready并返回来源 | supplement/m5.json |
| 模型路径确实不存在 | health degraded，语义503 MODEL_UNAVAILABLE；上传正文/关键词/下载仍正常；还原模型并重试通过 | cold-regression/03-review-after.json |
| 索引进程在processing后退出75 | DB处理声明存在、发布前无片段；新进程领回，attempts=2，同一代次唯一片段/查询/SHA通过 | supplement/m5.json及interrupted-job日志 |
| 正式文件fsync后、SQL提交前退出74 | DB无文件记录而原字节已落盘；重启将原文件及意图移入quarantine，字节一致且未自动导入 | supplement/m5.json及landed-before-db日志 |
| 正文重试与旧任务并发 | 三次普通重试保持一任务；正文重试提交generation=2，旧代次发布被阻止；最终唯一代次/来源/SHA通过 | cold-regression/03-review-after.json |
| 批量部分缺失/真实SQL写失败 | 缺失逐文件失败；SQL触发器使批次503，原归属整批保留；移除故障后重试成功、4原文件SHA与ready片段数保持 | supplement/batch.json、batch-rollback-http.json |
| 超限/无效文件/参数 | 400/413/415/422/404/409是预先声明的错误验收；返回正确，未记录为成功上传或非预期故障 | cold-regression/04-prepare.json |

历史实修继续引用真实旧证据：M6正文重试竞态修复前失败/修复后通过，见[evidence/m6/review-before-failed.json](evidence/m6/review-before-failed.json)和[code-review.md](code-review.md)；普通Chrome旧改名控件不可达及修复60d5350见[category-dialog-fix.md](category-dialog-fix.md)；批量整理f7496a4见[batch-organization.md](batch-organization.md)；冷构建旧Vite审计项/升级69944d3见[deployment-check.md](deployment-check.md)。不把这些历史修复编造成本轮新增修复。

## 剩余限制与交付条件

- 向量检索仍有泛化误返回。设备原问正确且默认去掉发布尾部；设备同义问分数0.523106，目标第一，但部分工作流程文档仍进入窗口；3组无关问题为空不代表所有未知问题为空。来源相关性也不保证，支持展开更多。
- SQLite精确向量遍历与单模型推理锁面向小资料集，未做大库压测；每文件最多2000片段，超过时失败仍可下载。上传内容不做重复文件识别，重复上传是新ID。
- PDF只名称检索与原文件/浏览器预览，正文/OCR不支持。预览接口3份原SHA本轮通过，阅读器显示依赖普通浏览器；没有新增Agent Chrome阅读器实测。用户汇总完成确认不补造具体预览截图/尺寸记录。
- 批量每次最多100份，刷新不保留勾选，归档选择弹窗只列活动文件；可在归档区批量调整归属但不恢复；并发归属以最后提交为准。扁平分类，不做目录树、权限、版本、问答或多服务。
- 本轮应用候选的Git源码独立空卷回归已完成，记录提交只增加文档/证据；目前无真实仓库remote和平台日志上传说明。后续由用户决定最终版本，锁定与上传继续暂缓。
