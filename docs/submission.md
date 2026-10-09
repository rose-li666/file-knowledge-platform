# 交付资料导航

公开仓库：[rose-li666/file-knowledge-platform](https://github.com/rose-li666/file-knowledge-platform)，main分支。考官取得源码后按根目录README启动，不需要开发者Windows目录、既有数据或测试ZIP。默认空库；测试脚本主动执行时才导入独立卷。源码包含Dockerfile、Compose、Python依赖锁、前端lock和固定模型revision，首次构建联网下载依赖/模型，运行离线。

| 交付内容 | 文件/证据 |
|---|---|
| 启动、配置、模型准备、失败处理、重建保留数据 | [README](../README.md)、[Dockerfile](../Dockerfile)、[Compose](../compose.yaml)、[环境示例](../.env.example) |
| 架构、取舍、组件来源、本人实现范围、真实问题复盘 | [delivery.md](delivery.md)、[model-spec.json](../model-spec.json) |
| 要求→页面/API→实测、待验证与限制 | [acceptance.md](acceptance.md) |
| API、请求响应与状态 | [m2-api.md](m2-api.md)、[m3-api.md](m3-api.md)、[m4-api.md](m4-api.md)、[m5-api.md](m5-api.md)、[batch-organization.md](batch-organization.md) |
| Git源码无缓存安装/模型下载、空卷、完整回归、review | [final-candidate-review.md](final-candidate-review.md)及其原始日志 |
| 最新语义对照与取舍、受影响回归 | [retrieval-round.md](retrieval-round.md)及before/after/p0/quality原始JSON |
| 页面截图、侧栏修复、窄屏与批量整理 | [ui-optimization.md](ui-optimization.md)、[category-dialog-fix.md](category-dialog-fix.md)、[batch-organization.md](batch-organization.md) |
| 用户人工确认（与自动化/Agent浏览器分开） | [user-validation.md](user-validation.md)、[manual-check.md](manual-check.md) |
| 技术限制与专项验证边界 | [remaining-acceptance.md](remaining-acceptance.md) |

## 统一资料的五组查询

实际通过新上传TXT/Markdown分片、持久化向量和容器HTTP检索获得；PDF在此轮不参与正文/向量。下表使用统一资料分类；原文与所有返回项见retrieval-round证据，排名不是预期值。

| 自然语言问题 | 目标文件 | 目标排名 |
|---|---|---|
| 交给同事审阅修改之前，应该怎样自查并描述测试结果？ | 01_代码提交规范_v2.1.md | 1 |
| 网络断了又提交同一份上传请求，服务怎样防止保存两次？ | 03_文件服务接口约定_v1.2.md | 1 |
| 上线刚启动，新版本要验证哪些用户操作才能放心交付？ | 02_发布检查清单_v1.4.md | 2 |
| 文档上传成功却查不到正文，数据换了嵌套结构，怎么补救而不用重传？ | 06_星桥项目_故障复盘_2026-09-21.md | 1 |
| 重建运行环境后以前的资料丢了，该怎样排查挂载和保住原有数据？ | 09_本地部署故障排查_v1.3.txt | 1 |

测试资料中的接口规范等是文档内容，不是平台新增需求；例如资料提到Idempotency-Key不代表本平台实现了上传幂等。平台重复上传按独立文件ID保存，无文件去重/版本管理。

## 限制与交付边界

语义结果可能混入高分无关流程文档、来源片段可能偏泛化。默认相对窗口可能隐藏低分相关资料，展开更多保留基础门槛候选；没有未知问法精度保证。PDF仅名称搜索/原字节预览下载，无正文提取/OCR；扫描件不识别。精确遍历、单索引/推理并发用于小资料集，未压测大库。无登录/权限、问答、版本、目录树或多服务。

用户已汇总确认人工验证完成，专项记录只保留实际原话，不补造尺寸、时间、截图或逐动作结果。PDF阅读器显示、普通浏览器“正文ready/向量failed”、低高度/窄屏键盘等专项人工明细未提供；大库性能和其他宿主系统未单独验证，不能追加通过结论。人工与自动化记录按来源分别保存，历史测试报告反映当时实际执行结果。
