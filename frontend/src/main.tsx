import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Health = { status: string; database: { status: string; probeCount: number }; model: { status: string } };
type Config = { maxUploadBytes: number; allowedExtensions: string[] };
type Document = {
  id: string; name: string; extension: string; mediaType: string; sizeBytes: number;
  sha256: string; uploadedAt: string; category: null; textStatus: string; vectorStatus: string; downloadUrl: string;
};
type Page = { items: Document[]; total: number; limit: number; offset: number };
type Upload = { key: string; file: File; state: 'waiting' | 'uploading' | 'saving' | 'done' | 'error';
  percent: number; message: string; retryable: boolean };
class ApiError extends Error {
  constructor(message: string, public retryable = false) { super(message); }
}
function errorFrom(body: unknown, fallback: string) {
  const data = body as { error?: { message?: string; retryable?: boolean }; detail?: unknown };
  return new ApiError(data?.error?.message ?? (typeof data?.detail === 'string' ? data.detail : fallback),
    data?.error?.retryable ?? false);
}
async function json<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  const body: unknown = await response.json();
  if (!response.ok) throw errorFrom(body, '请求失败，请刷新后重试');
  return body as T;
}
function size(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
function date(value: string) { return new Date(value).toLocaleString('zh-CN', { hour12: false }); }
function message(error: unknown) { return error instanceof Error ? error.message : '请求失败，请稍后重试'; }

function sendFile(file: File, progress: (percent: number) => void): Promise<Document> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open('POST', '/api/v1/documents');
    request.timeout = 180000;
    request.upload.onprogress = event => {
      if (event.lengthComputable) progress(Math.round(event.loaded / event.total * 100));
    };
    request.onload = () => {
      try {
        const body: unknown = JSON.parse(request.responseText);
        if (request.status === 201) resolve(body as Document);
        else reject(errorFrom(body, `上传失败（HTTP ${request.status}）`));
      } catch { reject(new ApiError('上传响应无法确认，请刷新文件列表核对后再试。')); }
    };
    request.onerror = () => reject(new ApiError('网络中断，保存结果尚未确认。请刷新文件列表核对后再试。'));
    request.ontimeout = () => reject(new ApiError('上传超时，保存结果尚未确认。请刷新文件列表核对后再试。'));
    const body = new FormData();
    body.append('file', file);
    request.send(body);
  });
}

function App() {
  const input = useRef<HTMLInputElement>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [configError, setConfigError] = useState('');
  const [health, setHealth] = useState<Health | null>(null);
  const [page, setPage] = useState<Page>({ items: [], total: 0, limit: 25, offset: 0 });
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState('');
  const [notice, setNotice] = useState('');
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [uploading, setUploading] = useState(false);
  const uploadLock = useRef(false);
  const [detail, setDetail] = useState<Document | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const detailRequest = useRef(0);
  const listRequest = useRef(0);
  const [downloadId, setDownloadId] = useState('');
  const [probeBusy, setProbeBusy] = useState(false);
  const [probeMessage, setProbeMessage] = useState('');
  async function loadConfig() {
    setConfigError('');
    try { setConfig(await json<Config>('/api/v1/config')); }
    catch (error) { setConfigError(message(error)); }
  }
  async function refresh(offset = 0) {
    const generation = ++listRequest.current;
    setLoading(true); setListError('');
    try {
      const result = await json<Page>(`/api/v1/documents?limit=25&offset=${offset}`);
      if (generation === listRequest.current) setPage(result);
    } catch (error) { if (generation === listRequest.current) setListError(message(error)); }
    finally { if (generation === listRequest.current) setLoading(false); }
  }
  useEffect(() => {
    void refresh(); void loadConfig();
    json<Health>('/api/v1/health').then(setHealth).catch(() => setHealth(null));
  }, []);
  function selectFiles(files: FileList | null) {
    if (!files || !config) return;
    const rows = Array.from(files).map(file => {
      const extension = file.name.split('.').pop()?.toLowerCase() ?? '';
      const problem = !config.allowedExtensions.includes(extension) ? '仅支持 PDF、TXT、Markdown。'
        : file.size === 0 ? '不能上传空文件。'
        : file.size > config.maxUploadBytes ? `文件超过 ${size(config.maxUploadBytes)} 上限。` : '';
      return { key: crypto.randomUUID(), file, state: problem ? 'error' as const : 'waiting' as const,
        percent: 0, message: problem, retryable: false };
    });
    setUploads(rows); setNotice('');
  }
  function changeUpload(key: string, values: Partial<Upload>) {
    setUploads(current => current.map(row => row.key === key ? { ...row, ...values } : row));
  }
  async function upload(rows = uploads.filter(row => row.state === 'waiting')) {
    if (uploadLock.current || rows.length === 0) return;
    uploadLock.current = true; setUploading(true); setNotice('');
    let successes = 0;
    try {
      for (const row of rows) {
        changeUpload(row.key, { state: 'uploading', percent: 0, message: '', retryable: false });
        try {
          await sendFile(row.file, percent => changeUpload(row.key, { percent,
            state: percent === 100 ? 'saving' : 'uploading' }));
          successes++;
          changeUpload(row.key, { state: 'done', percent: 100, message: '已保存，可下载' });
        } catch (error) {
          changeUpload(row.key, { state: 'error', message: message(error),
            retryable: error instanceof ApiError && error.retryable });
        }
      }
      if (successes) setNotice(`已保存 ${successes} 个文件。`);
      await refresh(0);
    } finally { uploadLock.current = false; setUploading(false); }
  }
  async function openDetail(id: string) {
    const generation = ++detailRequest.current;
    setDetail(null); setDetailError(''); setDetailLoading(true);
    try {
      const result = await json<Document>(`/api/v1/documents/${id}`);
      if (generation === detailRequest.current) setDetail(result);
    } catch (error) { if (generation === detailRequest.current) setDetailError(message(error)); }
    finally { if (generation === detailRequest.current) setDetailLoading(false); }
  }
  async function download(document: Document) {
    if (downloadId) return;
    setDownloadId(document.id); setNotice('');
    try {
      const response = await fetch(document.downloadUrl);
      if (!response.ok) throw errorFrom(await response.json(), '下载失败，请稍后重试');
      const url = URL.createObjectURL(await response.blob());
      const link = window.document.createElement('a');
      link.href = url; link.download = document.name;
      window.document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice(`已接收「${document.name}」，浏览器将保存文件。`);
    } catch (error) { setNotice(message(error)); }
    finally { setDownloadId(''); }
  }
  async function probe() {
    setProbeBusy(true);
    try {
      const saved = await json<{ id: number; value: string }>('/api/v1/m1/probes', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: `页面读写验证 ${new Date().toISOString()}` }),
      });
      const rows = await json<{ items: { id: number; value: string }[] }>('/api/v1/m1/probes');
      if (!rows.items.some(row => row.id === saved.id && row.value === saved.value)) throw new Error('写入后未读到相同记录');
      setHealth(await json<Health>('/api/v1/health'));
      setProbeMessage(`读写成功 · 记录 #${saved.id} 已保存并核对`);
    } catch (error) { setProbeMessage(message(error)); }
    finally { setProbeBusy(false); }
  }
  return <main>
    <header><span className="mark">K</span><strong>知识文件库</strong><span className="stage">文件管理</span></header>
    <section className="intro"><p className="eyebrow">YOUR DOCUMENTS, IN ONE PLACE</p><h1>让资料有处可寻。</h1><p>保存原始文件，查看资料信息，随时下载复用。</p></section>
    {notice && <div className="notice" role="status" aria-live="polite">{notice}</div>}
    <section className="upload-card" aria-labelledby="upload-title">
      <div><span className="label">收集资料</span><h2 id="upload-title">上传文件</h2><p>PDF、TXT、Markdown · {config ? `单个文件不超过 ${size(config.maxUploadBytes)}` : '正在读取上传限制…'}</p></div>
      <div className="upload-controls"><input ref={input} id="file-input" aria-label="选择上传文件" type="file" multiple accept=".pdf,.txt,.md,.markdown" disabled={uploading || !config} onChange={event => selectFiles(event.target.files)}/>
        <label htmlFor="file-input">选择文件</label><button disabled={uploading || !uploads.some(row => row.state === 'waiting')} onClick={() => void upload()}>{uploading ? '正在上传…' : '开始上传'}</button></div>
      {configError && <p role="alert" className="error">{configError}<button className="text-button" onClick={() => void loadConfig()}>重试读取限制</button></p>}
      {uploads.length > 0 && <div className="upload-queue" aria-live="polite">{uploads.map(row => <div className={`upload-row ${row.state}`} key={row.key}>
        <div className="upload-name"><strong title={row.file.name}>{row.file.name}</strong><small>{size(row.file.size)}</small></div>
        <div className="upload-feedback"><span>{row.state === 'waiting' ? '等待上传' : row.state === 'uploading' ? `上传中 ${row.percent}%` : row.state === 'saving' ? '传输完成，正在保存…' : row.message}</span>
          {(row.state === 'uploading' || row.state === 'saving') && <progress max="100" value={row.percent} aria-label={`${row.file.name} 上传进度`}/>}</div>
        {row.state === 'error' && row.retryable && <button disabled={uploading} className="secondary" onClick={() => void upload([row])}>重试</button>}
      </div>)}{!uploading && <button className="text-button" onClick={() => { setUploads([]); if (input.current) input.current.value = ''; }}>清空选择</button>}</div>}
    </section>
    <div className="library-layout"><section className="library" aria-labelledby="library-title">
      <div className="section-heading"><div><h2 id="library-title">全部文件 <span className="count">{page.total}</span></h2><small>原文件已保存 · 按上传时间排列</small></div><button className="secondary" disabled={loading} onClick={() => void refresh(page.offset)}>刷新列表</button></div>
      {listError && <div className="error notice" role="alert">{listError}<button className="text-button" onClick={() => void refresh(page.offset)}>重试</button></div>}
      {loading ? <div className="empty" role="status">正在加载文件…</div> : page.items.length === 0 ? <div className="empty"><span className="empty-icon">＋</span><h3>这里还没有文件</h3><p>选择上方的文件，开始保存第一份资料。</p></div> : <div className="table-wrap"><table><thead><tr><th>名称</th><th>分类</th><th>大小 / 上传时间</th><th>操作</th></tr></thead><tbody>{page.items.map(row => <tr key={row.id} className={detail?.id === row.id ? 'selected' : ''}>
        <td><div className="file-name"><span className={`file-badge ${row.extension}`}>{row.extension === 'markdown' ? 'MD' : row.extension.toUpperCase()}</span><button className="name-button" title={row.name} onClick={() => void openDetail(row.id)}>{row.name}</button></div></td>
        <td><span className="category">未分类</span></td><td><span>{size(row.sizeBytes)}</span><small>{date(row.uploadedAt)}</small></td>
        <td><button className="text-button" aria-label={`下载 ${row.name}`} disabled={!!downloadId} onClick={() => void download(row)}>{downloadId === row.id ? '下载中…' : '下载'}</button></td>
      </tr>)}</tbody></table></div>}
      {page.total > 25 && <div className="pagination"><button className="secondary" disabled={loading || page.offset === 0} onClick={() => void refresh(Math.max(0, page.offset - 25))}>上一页</button><span>{Math.floor(page.offset / 25) + 1} / {Math.ceil(page.total / 25)}</span><button className="secondary" disabled={loading || page.offset + 25 >= page.total} onClick={() => void refresh(page.offset + 25)}>下一页</button></div>}
    </section>
    <aside className="detail" aria-labelledby="detail-title"><span className="label">资料信息</span><h2 id="detail-title">文件详情</h2>
      {detailLoading ? <p role="status">正在加载详情…</p> : detailError ? <p className="error" role="alert">{detailError}</p> : detail ? <><h3 className="detail-name">{detail.name}</h3><dl>
        <dt>文件类型</dt><dd>{detail.extension.toUpperCase()}</dd><dt>分类</dt><dd>未分类</dd><dt>大小</dt><dd>{size(detail.sizeBytes)} <small>{detail.sizeBytes.toLocaleString()} 字节</small></dd><dt>上传时间</dt><dd>{date(detail.uploadedAt)}</dd><dt>SHA-256</dt><dd className="hash">{detail.sha256}</dd></dl><p className="saved-note">已保存，可下载。检索索引尚未建立。</p><button disabled={!!downloadId} onClick={() => void download(detail)}>{downloadId === detail.id ? '下载中…' : '下载原文件'}</button></> : <p className="detail-placeholder">点击文件名称，查看完整名称、上传时间和文件校验值。</p>}
    </aside></div>
    <details className="diagnostics"><summary>服务状态 <span className={`dot ${health?.database.status === 'ready' ? 'ok' : ''}`}/></summary><div><p>数据库：{health?.database.status ?? '未能确认'} · 本地模型：{health?.model.status ?? '未能确认'} · 验证记录：{health?.database.probeCount ?? '—'}</p><button className="secondary" disabled={probeBusy} onClick={() => void probe()}>{probeBusy ? '正在核对…' : '验证数据库读写'}</button><p role="status">{probeMessage}</p></div></details>
    <footer>知识文件库 · 原文件保存在持久化存储中</footer>
  </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
