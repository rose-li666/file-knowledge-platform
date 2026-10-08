# M4 关键词检索

范围：文件名及 TXT/Markdown 正文的字面子串检索，分类组合筛选，命中片段。PDF 仅名称搜索；本阶段不实现语义检索。

## 接口

`GET /api/v1/search/keyword?q=ENG-014&category_id=UUID&archived=false&limit=25&offset=0`

- q：1–200 字，去首尾空白，拒绝控制字符；空白/超长返回 422。
- category_id 可省略（全部分类）、UUID 或 unclassified；非法/不存在分类与列表接口一致，返回 422/404。
- archived 默认 false（只搜索未归档文件），true 只搜索归档区。
- limit 1–100，offset ≥0；文件名命中优先，再按上传时间及 ID 降序。没有语义相关性评分。
- NFKC + casefold 规范化后做字面包含；中文与完整编号不分词。空格、连字符、下划线保留，% 和 _ 不作通配符。

响应是文件元数据列表，增加 hit：

```json
{
  "items": [{
    "id": "文件 UUID",
    "name": "01_代码提交规范_v2.1.md",
    "textStatus": "ready",
    "textError": null,
    "textEncoding": "utf-8",
    "hit": {
      "fields": ["body"],
      "text": "# 代码提交规范\n\n文档编号:eng-014  \n版本:2.1…",
      "highlightStart": 15,
      "highlightEnd": 22
    }
  }],
  "total": 2,
  "limit": 25,
  "offset": 0,
  "query": "ENG-014",
  "bodyUnavailableCount": 0
}
```

上例仅展示形状，具体片段与偏移以实际响应为准。完整文件元数据继承 M3。fields 为 name/body 或两者；正文命中优先展示正文，否则展示名称。片段是实际匹配使用的规范化文本，所以英文可能小写、全角标点可能变半角；原文件及存储的 content 不改写。偏移为 Unicode 字符位置，前端按 code point 切片；React 文本节点与 mark 高亮不执行 HTML。

`bodyUnavailableCount` 是当前分类/归档范围内正文未就绪的非 PDF 文件数，帮助解释正文搜索覆盖不完整。没有结果返回 200、items=[]、total=0。数据库异常返回 503 SEARCH_UNAVAILABLE。

`POST /api/v1/documents/{id}/text/retry`：重新提取 TXT/Markdown，返回文件详情。无效原始编码仍返回 textStatus=failed 和原因，不伪称重试成功；文件缺失 404、PDF 409 TEXT_NOT_SUPPORTED，数据库提交失败 503。重试不会修改原文件或归档/分类。

## 保存与提取隔离

上传沿用 M2 的原文件持久化与元数据事务，提交成功后才开始独立的正文提取事务。正文异常不回滚上传，返回 201 和 textStatus=failed；下载照常校验并返回原始字节。提取事务无法提交时上传仍返回 201、not_started 及“正文处理尚未确认”提示，允许刷新详情后重试。

- TXT/Markdown：UTF-8（可 BOM）；带 BOM 的 UTF-16；无 BOM 且 UTF-8 解码失败时尝试 GB18030，全部严格解码。拒绝二进制控制字符，不用替换字符掩盖错误。UTF-32 不支持。
- textStatus：not_started → ready / failed；PDF → not_supported。textError 记录可理解的原因，textEncoding 记录实际解码方式。
- vectorStatus 仍 not_started；正文 ready 不表示语义向量已经生成。
- 原文件保存与正文处理分离；失败文件仍可按名称搜索。归档只通过即时 SQL 过滤排除，不删除正文；恢复立刻可搜。

## 持久化与部署

schema user_version 升级到 2：documents 新增可空 text_error/text_encoding；新增 document_texts(document_id PRIMARY KEY/FK,content,search_content)，每文件一条正文。原有 ID/哈希/存储键/分类/归档不变。启动为此前 not_started 的文件补建正文，不会自动重试 failed 状态；持久化任务恢复、向量片段去重及故障注入仍在 M5。

SQLite 参数化 instr 匹配原名与持久化的 search_content。名称规范化函数由每个数据库连接注册，不依赖 FTS 的中文或编号分词。该实现扫描过滤范围，适合本次少量验收资料；大库需更适合的检索索引，未声称大规模性能通过。

部署保持一个服务、一个 Uvicorn worker；正文处理用进程内锁串行执行，下载与元数据服务不依赖模型成功加载。没有新增队列服务、外部数据库或密钥。全部正文保存在已有 /data 具名卷；上传资料不发送外部服务。
