# M5 索引与语义 API

业务数据库 schema=3，新增 index_jobs（document_id 主键，generation/state/attempts/updated_at）及 chunks（document_id+ordinal 复合主键，generation/heading/text/embedding/model_revision）；documents 增加 vector_error/chunk_count。正文继续独立保存在 document_texts，每文件一行。向量是标准化 512 维 little-endian float32 BLOB。

## 状态和响应

上传 HTTP 201 表示原始字节和元数据已保存，同时事务提交 pending 索引任务。textStatus 和 vectorStatus 独立：正文 ready、向量 failed 时，详情返回 textStatus=ready、vectorStatus=failed、vectorError 和 downloadUrl；页面明确显示正文可搜索、索引失败、原文件可下载和重试索引。PDF 为 not_supported。上传保存进度与后台索引进度分别显示，界面每 2 秒更新可见排队/处理中的文件。

索引 pending → processing → ready / failed。一条文档只有一条任务；processing 先独立提交，再读取正文、分片和本地模型编码，最后以当前 generation/state 核对，事务内替换片段并更新 ready。失败不影响正文或原文件，旧代次不会参与语义结果。重启将 processing 回到 pending；failed 保留错误，需要手动重试。

`POST /api/v1/documents/{id}/index/retry` 返回 202 DocumentResponse。pending/processing 原样返回，避免重复排队；failed/ready 增加 generation 后排队，当前片段数置 0，成功后原子替换。PDF 409，未知文件 404，任务提交异常 503（提示先刷新核对）。`POST .../text/retry` 可重试正文，并提交索引任务。

`GET /api/v1/search/semantic?q=自然语言问题&category_id=分类UUID&archived=false&limit=10&offset=0&min_score=0.45`。q 为 1–200 字；limit 1–25；min_score 0–1。分类支持 unclassified；缺省仅未归档。返回 items（DocumentResponse + score + sources）、total/limit/offset/query/minScore/vectorUnavailableCount/modelRevision；每 sources 包含 ordinal/generation/heading/text/score，最多 2 个原文片段。按文件最佳片段点积排序，分数不是概率，无关键词回退或 reranker。只检索 ready、任务代次一致且当前模型版本的片段。空范围/低于阈值返回 200 空数组；模型未加载或向量计算/存储异常 503，关键词和下载接口仍工作。

## 分片与运行约束

按段落和 Markdown/中文标题组织，长段按 tokenizer offset 窗口切片，最多 300 个正文 token、30 token 重叠，标题+片段实际 token 不超过模型长度。单文档超过 2000 个片段索引失败。/data 所有权跨进程锁拒绝多个 Web worker，共享本地推理锁，后台消费 loop 单并发；数据库任务持久化，无 Redis/外部队列服务。

原文件落盘后 SQL 未提交的真实进程中断已验证：启动对账将无记录正式文件及意图隔离到 quarantine，保留字节，不自动导入/删除。已提交且哈希一致仅清理残留意图，异常保留并在 health.uploadRecovery 报告。/data 下全部业务存储位于 Compose 命名卷，模型随镜像。

## 验证执行

从项目根目录执行 `python scripts/run_m5_docker.py --zip 测试ZIP路径`，日志在项目旁 m5-docker/时间目录；无需 PowerShell 脚本执行策略。Docker 验证容器调用主应用真实 HTTP、新上传全部 10 份资料；故障进程仅使用 /tmp/m5-faults，不更改主应用任务或模型。模型推理异常、processing 后进程退出 75、正式落盘后进程退出 74 在 scripts/m5_fault_server.py 中注入；生产 app 没有故障开关。实际异常、重启和重试运行日志会从验证容器复制出来。已有构建加 --skip-build。

没有宿主机 Python 时，准备项目内 test-documents.zip 后可执行：

```sh
docker compose run --no-deps --name platform-m5-check -v ./test-documents.zip:/fixtures/documents.zip:ro app python scripts/verify_m5.py --zip /fixtures/documents.zip --data-dir /tmp/m5-verification --report /tmp/m5-reports/results.json
docker cp platform-m5-check:/tmp/m5-reports ./reports-m5
docker rm platform-m5-check
```

前两条命令读取镜像和测试资料，不要求旧业务数据；第 3 条仅移除该次验证容器。再次验证请换容器名或先移除已经完成的验证容器。普通浏览器操作、窄屏和空数据卷/重建回归另行报告。
