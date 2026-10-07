# M3 分类与归档接口

所有路径前缀 `/api/v1`。分类扁平、单文件至多归属一个分类；`null` 表示未分类。暂不提供分类删除或目录树。

| 请求 | 行为 / 返回 |
| --- | --- |
| GET /categories | `{items:[{id,name,activeCount,archivedCount}],unclassified:{activeCount,archivedCount}}` |
| POST /categories | `{"name":"工程规范"}` → 201 分类对象 |
| PATCH /categories/{id} | `{"name":"开发规范"}` → 200 分类对象 |
| PATCH /documents/{id}/category | `{"categoryId":"UUID"}` 或 `{"categoryId":null}` → 200 文件详情 |
| GET /documents | 默认未归档；保留 limit/offset；`category_id=UUID` 或 `unclassified` 结合筛选 |
| GET /documents?archived=true | 只列归档文件，也支持 category_id/limit/offset |
| POST /documents/{id}/archive | 200 文件详情；首次写 UTC archivedAt，重复归档不改时间 |
| POST /documents/{id}/restore | 200 文件详情；archivedAt=null，保留分类；重复恢复也成功 |
| GET /documents/{id}、/{id}/download | 继续支持归档文件；原始字节及完整性校验规则与 M2 相同 |

文件详情和列表项增加 `category:{id,name}|null`、`archivedAt:ISO8601|null`。例如移动成功：

```json
{
  "id": "文件 UUID",
  "name": "01_代码提交规范_v2.1.md",
  "category": {"id": "分类 UUID", "name": "开发规范"},
  "archivedAt": null,
  "textStatus": "not_started",
  "vectorStatus": "not_started"
}
```

上例仅展示新增字段；真实响应还保留 M2 的类型、大小、上传时间、SHA-256 和 downloadUrl。分类改名会立即反映在文件列表/详情中，不复制名称到文件表。归档只更新元数据，移动也不改原文件、上传时间或索引状态；搜索尚未实现，将在 M4 同样默认排除归档。

名称先 NFKC 规范化、去首尾空白，再以 casefold 键判重，规范化后 1–80 字；不允许控制字符和系统名“未分类”。冲突 409 CATEGORY_NAME_EXISTS；非法名称 422；缺失分类/文件 404；数据库异常 503 DATABASE_UNAVAILABLE。业务错误结构 `{error:{code,message,retryable}}`，UUID/请求结构错误使用 FastAPI 422 detail，页面均转换为清晰提示。

数据库 `categories(id,name,name_key UNIQUE)`；documents 增加 `category_id NULL REFERENCES categories(id) ON DELETE RESTRICT`、`archived_at NULL`，按分类与归档建立索引。升级由单 worker 在启动时持有 BEGIN IMMEDIATE 事务执行，user_version=1；失败中止启动，不删除旧表。

页面分类管理、文件详情移动、列表/详情归档与恢复均等待 API 成功后刷新列表和分类计数；操作失败显示错误，允许再次操作。文件库/归档区与分类筛选写入 URL；整页刷新后恢复条件并重新请求持久化数据。
