# 文件管理与知识检索平台

一个 Docker 服务，提供 React 页面、FastAPI 接口、SQLite 数据库和本地文本向量模型。支持 PDF/TXT/Markdown 上传下载、扁平分类、归档恢复、关键词和语义检索。无需预置文件、数据库或宿主机 Python/Node。

## 启动

需要 Docker Engine / Docker Desktop（Linux 容器）和 Docker Compose v2。下载源码后，在包含 `Dockerfile`、`compose.yaml` 的项目根目录执行：

```sh
docker compose up --build -d
```

打开 http://localhost:8000 。第一次构建需访问 Docker Hub、npm、PyPI、PyTorch CPU 包和 Hugging Face 固定版本模型；模型约 96 MB，下载后写入镜像，运行时离线加载。网络需要代理时，在 Docker Desktop/Engine 中配置可用代理后再构建。构建失败先看错误所在下载步骤，无需清除数据卷。

默认配置可直接启动。可选复制 `.env.example` 为 `.env`，修改 `APP_PORT`（页面端口，默认 8000）和 `MAX_UPLOAD_BYTES`（单文件字节限制，默认 20971520）。无需密钥；新增密钥只从环境变量读取，勿提交 `.env`。

```sh
docker compose ps
docker compose logs --tail=100 app
```

首次 CPU 模型加载期间页面尚未服务；健康检查启动等待窗口为 90 秒。模型加载失败仍提供文件管理/关键词搜索，健康响应标记 degraded，语义接口明确报错。容器中 Uvicorn 固定 `--workers 1`；索引任务单并发，模型推理锁串行。不要增加 worker 或同时启动两个进程共享同一 DATA_DIR，目录所有权锁会拒绝第二个实例。

## 操作

1. 选择 PDF、TXT、`.md` / `.markdown` 文件并开始上传，查看进度和保存结果。支持多选逐个上传。
2. 点击“管理分类”创建分类，成功后点“添加文件”，按名称和原分类查找、勾选多个文件，统一“移入此分类”；分类页也保留入口。每个文件只有一个主分类，移动会改变原归属。列表可勾选多个文件并“移动分类”（每批最多100个）；失败项明确显示并可重试。先选分类再打开管理会自动填入原名。侧栏分类独立滚动，窄屏使用分类下拉筛选；文件详情仍支持单文件移动和下载。详见 `docs/batch-organization.md`。
3. 选择关键词搜索（名称和 TXT/Markdown 正文，支持中文/编号）或语义搜索（描述需求，返回来源文件、原文片段及相似度），可同时筛选分类。
4. TXT/Markdown 显示等待索引、处理中、可语义检索或失败。正文已就绪但向量失败时仍可关键词查找和下载，在详情重试索引。
5. 归档后默认列表和两种搜索排除文件；在归档区可找回和下载，恢复后重新参与检索。筛选/问题保存在页面 URL，刷新保留。

空数据卷会显示空列表，上传第一份资料即可使用。PDF 支持名称搜索、原文件下载及详情中的浏览器在线预览，不提取正文。预览依赖浏览器PDF阅读器，不能显示时下载查看；扫描件不会OCR。文本支持 UTF-8、带 BOM 的 UTF-16、GB18030；失败不损坏原文件。

## 持久化与崩溃处理

Compose 的 `platform_data` 命名卷挂载 `/data`：`db/platform.sqlite3` 保存业务元数据、正文、索引任务和 512 维 float32 向量；`uploads` 保存原始字节；`tmp` 保存上传中间文件及意图；`quarantine` 保留未提交文件供检查。模型在镜像 `/opt/models/bge`。

```sh
docker compose restart app
docker compose up -d --force-recreate
```

这两个命令保留数据卷。勿对需要保留的资料执行 `docker compose down -v`。停机备份应包含整个数据卷；在线仅复制 sqlite 主文件会遗漏 WAL，不作为备份方案。

上传先 fsync 临时字节和意图，再原子移动到 uploads，最后同一 SQL 事务提交文件记录与索引任务。成功确认前崩溃：已有且哈希一致的数据库记录保留，清理残留意图；正式文件无数据库记录则移入 quarantine，保留字节和意图，不自动导入也不删除；临时文件同样隔离。提交结果不确定返回 503 并提示刷新核对。索引 processing 任务在重启时回到 pending，失败任务保留错误并需手动重试。片段主键是文件 ID+顺序号，代次检查及原子替换防止重试产生重复或半成品索引。

## 验证与资料

真实考核 ZIP 不随源码提交，正常启动不需要它。将资料置于任意可读路径后，验证脚本通过 `--zip` 指定；日志 UTF-8，无需改变 Windows 执行策略。

M5 验证脚本会新上传全部资料到独立临时数据库/目录的分类，核对下载 SHA-256、分片向量持久化、5 组改写问题排名、过滤；进程故障实验使用独立测试数据目录，不影响主服务数据。使用当前镜像执行（先将测试 ZIP 复制为项目目录 `test-documents.zip`）：

```sh
docker compose run --no-deps --name platform-m5-check -v ./test-documents.zip:/fixtures/documents.zip:ro app python scripts/verify_m5.py --zip /fixtures/documents.zip --data-dir /tmp/m5-verification --report /tmp/m5-reports/results.json
docker cp platform-m5-check:/tmp/m5-reports ./reports-m5
docker rm platform-m5-check
```

这些命令启动独立真实 HTTP 服务并复制完整报告后清理验证容器；再次运行需换容器名或先清理已完成的验证容器，详见 `docs/m5-api.md`。历史各阶段报告在 `docs/m1-report.md` 至 `docs/m6-report.md`，含实测与未测项；历史本机开发命令仅在 `docs/development-history.md`，不是启动依赖。M6 空数据卷部署、重启/重建、错误回归和审查证据见 `docs/m6-report.md`；浏览器验收状态同样在报告中记录。

## 实现范围与限制

本人实现文件保存及崩溃对账、分类归档、正文提取、分片任务、向量存储与精确检索、API、React 操作页面和验证脚本。使用开源组件：[FastAPI](https://github.com/fastapi/fastapi)、[React](https://github.com/facebook/react)、[SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy)、[Sentence Transformers](https://github.com/huggingface/sentence-transformers)、[BGE 模型](https://huggingface.co/BAAI/bge-small-zh-v1.5)。包版本锁定在 requirements 和前端 lock 文件；模型版本及查询前缀在 model-spec.json。未复制现成知识库项目。

SQLite BLOB 保存标准化 512 维向量，NumPy 点积精确检索，以文件最佳片段排序，展示最多 2 个来源片段；基础相似度阈值0.45，默认最多5项且距首位得分不超过0.12；可展开原门槛下全部候选（25项/页）。来源片段距文件最佳得分不超过0.08，最多2段。相似度非相关性概率，窗口可能隐藏低分相关项；实测与局限见 `docs/retrieval-quality.md`。适合少量考核文档，无 ANN、大库性能承诺或统一排序精度保证。单文件最多 2000 片段，过多时索引失败仍保留原文件。暂不做用户权限、问答、文件版本、PDF 正文/OCR；当前用于本地考核演示。


## 独立回归与常见失败

默认启动为空库，不自动导入 `scripts/fixtures`；这些虚构资料仅用于主动执行测试。可选自动化验收需要宿主机Python3（仅编排Docker，应用启动不需要它）：

```sh
python scripts/run_m6_docker.py --zip ./test-documents.zip
```

脚本为每次运行生成独立Compose项目、随机端口和新命名卷；构建→健康→真实HTTP/模型→重启→重建逐步执行，任一步失败停止依赖步骤，UTF-8日志含命令、退出码和耗时。结束只停止自建项目，保留其测试卷和报告。历史 `run_m1_docker.py` 至 `run_m5_docker.py` 现在均转入这套隔离回归，不连接演示端口；历史报告中的旧命令对应当时提交。`--no-cache` 强制重新安装依赖及下载模型。独立项目每次构建自己的镜像，普通回归可以使用依赖层缓存；不覆盖演示镜像。

下载失败：查看日志中具体 registry/npm/pip/Hugging Face 地址，检查Docker代理/DNS/网络，再重试失败的构建步骤。PowerShell把Docker进度stderr显示成红字并不代表失败，以进程退出码及最后错误为准。无需降低执行策略，使用上面Python命令。端口占用时在 `.env` 更改 `APP_PORT` 后启动。模型下载在构建期间完成，运行时不联网补下载；缺失时健康degraded，文件管理仍可用，检查镜像构建日志后重新构建/创建容器。数据目录写入错误时检查命名卷权限，不在两个服务间共享同一目录。

更新源码后运行 `docker compose up --build -d`，保持同一Compose项目名以使用原卷。独立考官环境直接用干净源码和新Compose项目即可，ZIP不属于启动依赖。验收表、人工检查步骤和用户记录分别见 `docs/acceptance.md`、`docs/manual-check.md`、`docs/user-validation.md`。

候选Git源码最新完整回归与审查见 `docs/final-candidate-review.md`：独立空卷无缓存部署、上传下载SHA、检索、批量整理、故障恢复及重启重建证据。最终版本暂未锁定，剩余交付条件见 `docs/remaining-acceptance.md`。
