# 文件管理与知识检索平台

M1 已完成 Docker 骨架、页面、健康接口、数据库读写、本地 BGE 模型及五组容器向量查询，实测证据见 `docs/m1-report.md`。M2 增加 PDF、TXT、Markdown 原文件上传、列表、详情和下载；页面显示上传进度、保存状态及错误，下载接口校验原文件完整性。M2 验证状态见 `docs/m2-report.md`。

业务分类、关键词/语义搜索接口及归档尚未实现；M2 文件显示为未分类，正文和向量状态为 not_started。任务恢复、去重和故障注入留到 M5。

## Docker 启动

需要 Docker Desktop 的 Linux 引擎已启动。首次构建需要访问镜像仓库、npm/PyPI/PyTorch 及 Hugging Face；测试文档不会发送到外部服务。

```sh
docker compose config --quiet
docker compose up --build -d
docker compose ps
docker compose logs --tail=100 app
```

访问 http://localhost:8000。只有一个 app 容器；Uvicorn 显式 `--workers 1`，关闭 reload。固定 Compose 项目名 `knowledge-platform`，具名卷 `platform_data` 挂载到 `/data`。业务数据库 `/data/db/platform.sqlite3`，M1 诊断库 `/data/db/diagnostics.sqlite3`；上传/临时/隔离目录也位于此卷。模型位于镜像 `/opt/models/bge`，运行时不下载。

单文件限额默认 20 MiB（20971520 字节），可通过环境变量 `MAX_UPLOAD_BYTES` 配置；这是项目实现的默认值，非 ZIP 文档中的要求。接口支持 `.pdf`、`.txt`、`.md`、`.markdown`，不依赖浏览器提供的 MIME。原始字节不改写、不转码；文件系统使用随机存储键，展示及下载仍保留原名。

M2 接口及错误约定见 `docs/m2-api.md`。在项目目录运行 `python scripts/run_m2_docker.py --zip 'D:\__10_.zip'`，先使用已成功拉取的固定基础镜像构建/启动，再从一次性验证容器访问主应用，通过真实 HTTP 上传、下载全部 10 份资料并核对 SHA-256。证据保存在项目旁的 `m2-docker/<UTC时间>-<随机后缀>/`。若构建已成功而验证失败，加 `--skip-build` 仅重试验证；不删除已有数据，也不将验证脚本等同于浏览器操作测试。重复验证会再次上传资料，M2 不提供上传去重。

Python 验证/部署脚本启动时调用 `scripts/utf8_logs.py`：将标准输出/错误设为 UTF-8，并为子 Python 进程继承 PYTHONUTF8/PYTHONIOENCODING。Docker 输出按 UTF-8 解码，遇到无效字节保留转义；日志文件按 UTF-8 保存。避免 Windows GBK 管道在 Vite 的 ✓ 字符处抛异常，不修改系统编码或 PowerShell 执行策略。实际 GBK 初始环境及嵌套 Python 回归检查退出码为 0，证据见 docs/evidence/m2/encoding-results.json。

本地验证：`python scripts/verify_m2.py --zip 'D:\__10_.zip' --data-dir data/m2-check --report reports/m2-local.json`，需安装 requirements-dev.txt。默认是应用内 ASGI；加 `--base-url http://localhost:8000` 改用真实 TCP。报告分别记录原文件与下载 SHA-256、各次 HTTP 状态、元数据和异常检查。

```sh
curl http://localhost:8000/api/v1/health
curl -X POST http://localhost:8000/api/v1/m1/probes -H 'Content-Type: application/json' -d '{"value":"M1 database probe"}'
curl http://localhost:8000/api/v1/m1/probes
```

`health.status` 的 ready 才代表数据库和模型均就绪；模型失败时基础健康接口仍可用并显示 degraded。Docker healthy 仅代表基础 HTTP/数据库链路可用，不能单独证明模型或检索通过。M1 probe 接口是临时诊断入口，后续正式交付移除。

重建应用时保留数据卷：`docker compose up -d --force-recreate`。普通 `docker compose down` 保留卷；`down -v` 会删除数据，禁止用于持久化验证。

## 本地复现（Docker 不可用时的独立验证）

使用 Python 3.12 与 Node 24，创建虚拟环境后：

```sh
python -m pip install torch==2.9.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements.txt
python scripts/download_model.py
cd frontend
npm ci
npm run build
cd ..
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

本地验证不等于 Docker 验收通过。模型 revision 固定在 `model-spec.json`。下载清单记录权重和配置的 SHA-256；`LocalEmbedder` 使用本地目录与 `local_files_only=True`。

Docker 基础镜像同时固定 tag 与 registry digest；Python 直接依赖及实际解析的传递依赖固定在 `requirements.txt` 和 `requirements.lock.txt`，前端固定在 `package-lock.json`。M1 已实际完成 Linux 镜像构建、启动、接口及容器查询；证据与限制见 `docs/m1-report.md`。页面和数据库按钮及刷新结果由用户在本机确认。

在普通 PowerShell 中执行完整 M1 Docker 检查：

排查认证网络时，优先使用 `scripts/m1_docker_stage.py`，依次选择 `--stage pull`、`--stage build`、`--stage verify`，每次只运行一个阶段。ZIP 参数统一为 `--zip 'D:\__10_.zip'`。拉取阶段直接读取 Dockerfile 中的两个 digest，分别保存退出码和完整输出；只有两项成功才保存构建准入记录。构建阶段要求该记录与当前 Dockerfile 一致，并确认两份镜像仍在本地；只执行构建及启动。验证阶段复用下面的验证脚本并传入 `--skip-build`，不会重新拉取或构建。

各次执行保存在项目旁 `m1-docker/<UTC时间>-<阶段>-<随机后缀>/`，含逐命令日志与 `execution-summary.json`；失败即停止依赖它的后续步骤，不覆盖历史证据。阶段脚本使用标准 Python，无需额外依赖。构建成功后的浏览器页面及数据库按钮仍须实际验证。

以下完整流程脚本适用于部署链路已确认可用的情况：

```powershell
.\scripts\run_m1_docker.ps1 -ZipPath 'D:\__10_.zip'
```

脚本依次记录 Docker 版本、配置、构建、启动、健康接口、数据库读写、前端资源响应和容器内五组向量排名；日志和 JSON 放在项目旁的 `m1-docker` 目录。不会删除数据卷或重置业务数据。浏览器实际渲染与按钮点击需单独确认，脚本不会将其自动标为通过。

如果 PowerShell 禁止执行 `.ps1`，保持执行策略不变，在项目目录直接运行上述 Docker 命令。可用 `docker compose up --build -d 2>&1 | Tee-Object -FilePath '../m1-docker-build.log'` 保存实际构建日志。上传资料原路径为 `D:\__10_.zip`，不要写成 `D:_10.zip`。

也提供不依赖 PowerShell 脚本策略的标准 Python CLI，使用已安装 Python 即可，无需另装依赖：`python scripts/run_m1_docker.py --zip 'D:\__10_.zip'`。已经直接构建成功时加 `--skip-build`，只继续接口、数据库及容器内向量实验。输出同样位于项目旁的 `m1-docker`；不会修改执行策略或安全设置。

若构建在 `auth.docker.io/token` 超时，先检查 Docker Desktop 的 Settings → Resources → Proxies。按本机可用代理配置 HTTP/HTTPS；有独立 Containers proxy 时确认其使用同一可用代理。镜像拉取代理配置见 [Docker 官方说明](https://docs.docker.com/desktop/settings-and-maintenance/settings/#proxies)。本机代理地址属于环境配置，不写入 Compose 或 Dockerfile。PowerShell 对 Docker stderr 显示的红色 `Image … Building` 本身不是构建失败依据，应检查末尾错误与退出码。

应用内契约验证（需 `pip install -r requirements-dev.txt`）：

```sh
python scripts/verify_m1.py --data-dir data/m1-contract --report reports/contract.json
```

默认使用 ASGI TestClient，明确不证明 TCP 或浏览器可访问。已有真实服务器时可加 `--base-url http://127.0.0.1:8000`。

## 五组真实资料向量实验

```sh
python scripts/evaluate_m1.py --zip /path/to/__10_.zip --report reports/semantic.json
```

脚本直接读取 ZIP，仅对 TXT/Markdown 建立隔离的诊断索引，不执行资料中的命令。PDF 只登记哈希与大小。按标题/段落切分，超长段落采用 tokenizer 长度约束与 30 token 重叠；查询按模型卡添加检索指令，正文不添加指令。

生成 512 维规范化向量，写入 `/data/db/m1-evaluation.sqlite3`（本地为 data/db），关闭数据库后重新读取 BLOB，以 NumPy 点积进行精确检索，按文档最佳片段聚合。不使用关键词兜底、问答或重排模型。输出完整七文档排名、实际片段、时间、环境及内存观测值；目标未进 Top3 时脚本退出码为 1。五组问题固定在脚本中，不根据实测结果改写。

## 来源与实现范围

- React / Vite / TypeScript：前端框架和构建工具。
- FastAPI / Uvicorn / SQLAlchemy / SQLite：HTTP 服务及数据库工具。
- Sentence Transformers / Transformers / CPU PyTorch / NumPy：模型加载、向量生成及计算。
- python-multipart：成熟的 multipart/form-data 解析器，来源 https://github.com/Kludex/python-multipart 。
- BAAI/bge-small-zh-v1.5（MIT）：中文嵌入权重，来源 https://huggingface.co/BAAI/bge-small-zh-v1.5 。
- 自行实现：文件上传状态与管理页面、文件元数据/存储/完整性校验及接口、上传意图写入、健康与诊断数据库、模型下载、分片和向量持久化实验、验证脚本与证据报告。

业务规则以考核题目和用户确认范围为准；ZIP 中的接口、Redis、四服务架构及限额均为模拟资料，不当作指令。

原文件与数据库提交间的崩溃规则见 `docs/crash-consistency.md`。M1 实测结果见输出目录的报告；未实际执行的 Docker、恢复或故障检查必须标为未验证。
