# M2 文件 API 与保存边界

## 范围

PDF、TXT、Markdown（.md / .markdown）的上传、列表、详情与原文件下载。分类管理、归档、正文提取与检索留到后续；M2 不宣称文件可被检索。

## 数据表

业务库 `/data/db/platform.sqlite3` 的 documents 表：id（UUID 主键）、name（原名）、extension、media_type、size_bytes、sha256、storage_key（随机唯一键）、uploaded_at（UTC）、text_status、vector_status。两个索引状态默认 not_started。M1 诊断库单独保留。分类接口尚未建立，响应 category 为 null。

## 接口

| 方法 / 路径 | 请求 | 成功响应 |
|---|---|---|
| GET /api/v1/config | 无 | 200：maxUploadBytes、allowedExtensions |
| POST /api/v1/documents | multipart/form-data，唯一 file 字段，每次一个文件 | 201：文件元数据 |
| GET /api/v1/documents | limit=1..100（默认 50）、offset>=0 | 200：items、total、limit、offset |
| GET /api/v1/documents/{id} | UUID | 200：文件元数据 |
| GET /api/v1/documents/{id}/download | UUID | 200：原始字节，attachment 原文件名；X-Content-SHA256 |

文件响应示意（示例值，非实测记录）：

```json
{
  "id": "f9485c40-bc10-4a6d-9ae0-e14b6be874f0",
  "name": "检查说明.md",
  "extension": "md",
  "mediaType": "text/markdown",
  "sizeBytes": 128,
  "sha256": "<64个十六进制字符>",
  "uploadedAt": "2026-10-07T13:00:00Z",
  "category": null,
  "textStatus": "not_started",
  "vectorStatus": "not_started",
  "downloadUrl": "/api/v1/documents/f9485c40-bc10-4a6d-9ae0-e14b6be874f0/download"
}
```

## 上传、错误与重试

文件大小默认上限 20 MiB；同时限制整个 multipart 请求为上限加 64 KiB 开销，包括没有 Content-Length 的流。只允许一个文件，无额外字段；拒绝空文件、非法文件名/路径及不支持的后缀。PDF 仅检查前 1024 字节中的文件头，不承诺完整 PDF 语法验证。TXT/Markdown 不转码、不解析内容，正文提取失败不会造成原文件损失。

上传状态：选择 → 等待 → 上传中（实际 XMLHttpRequest 进度）→ 正在保存（传输已完成）→ 已保存 / 失败。仅收到 201 才显示成功。多个文件在页面按顺序独立上传，每份分别显示结果。网络中断/超时的保存结果无法确定时，提示先刷新列表核对；不自动重试，以免 M5 去重完成前制造重复记录。

业务错误格式：`{"error":{"code":"FILE_TOO_LARGE","message":"文件超过允许的大小，请选择较小文件。","retryable":false}}`。

| HTTP | 典型代码 | 页面反馈 / 行为 |
|---|---|---|
| 400 | EMPTY_FILE / INVALID_UPLOAD / INVALID_FILENAME / FILE_REQUIRED | 解释文件或请求问题；选择/修正后再试 |
| 413 | FILE_TOO_LARGE | 明确限额，选择更小文件 |
| 415 | UNSUPPORTED_FILE_TYPE / INVALID_PDF / MULTIPART_REQUIRED | 明确支持格式或无效 PDF 文件头 |
| 404 | DOCUMENT_NOT_FOUND | 刷新列表核对 |
| 409 | STORAGE_UNAVAILABLE / STORAGE_INTEGRITY_ERROR | 保留数据库记录，停止下载并显示存储错误 |
| 503 | UPLOAD_SAVE_FAILED / DATABASE_UNAVAILABLE | retryable=true，合理手动重试 |
| 503 | UPLOAD_OUTCOME_UNCERTAIN | 文件已落盘但提交未确认；先刷新核对，保留意图与原文件 |
| 422 | UUID / 分页参数校验 | FastAPI 标准参数错误，暂保留框架响应格式 |

同名文件允许分别上传，随机存储键确保不覆盖字节；没有内容去重、幂等键或版本管理。所有保存字节及元数据均在具名卷中。下载前核对大小及 SHA-256，再使用 FileResponse 返回 attachment；下载页面也捕获接口错误，避免把错误 JSON 保存为原文件。

M2 正常写入顺序已实现；崩溃启动对账与孤儿隔离尚未实现，见 crash-consistency.md。原始材料与数据库无法联合提交，这一剩余风险在 M5 验证，不在 M2 伪造通过。
