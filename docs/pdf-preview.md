# PDF预览范围

GET /api/v1/documents/{id}/preview只接受PDF。复用下载的存储路径、大小、SHA检查，返回application/pdf、inline和nosniff；TXT/MD返回409。三个统一资料PDF的预览实际字节均与数据库SHA一致，HTTP检查退出0。详情先检查HTTP错误并取Blob，再交浏览器阅读器；异步请求代次与Blob释放避免关闭后串入另一文件。

Agent内置浏览器390px入口可点击、请求成功，但嵌入区未渲染PDF页面，因此不宣称阅读器显示通过。普通Chrome与移动浏览器渲染待用户核对，页面提供下载替代路径。未引入PDF.js/外部服务；不做文本提取、扫描件OCR或PDF语义检索，避免扩展挤占核心验收时间。
