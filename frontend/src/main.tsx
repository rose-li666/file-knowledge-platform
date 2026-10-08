import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Health = { status: string; database: { status: string; probeCount: number }; model: { status: string } };
type Config = { maxUploadBytes: number; allowedExtensions: string[] };
type Category = { id: string; name: string; activeCount: number; archivedCount: number };
type Categories = { items: Category[]; unclassified: { activeCount: number; archivedCount: number } };
type Document = {
  id: string; name: string; extension: string; mediaType: string; sizeBytes: number;
  sha256: string; uploadedAt: string; category: { id: string; name: string } | null; archivedAt: string | null;
  textStatus: string; textError: string | null; textEncoding: string | null; vectorStatus: string; vectorError: string | null; chunkCount: number; downloadUrl: string;
  score?: number; sources?: { ordinal: number; heading: string; text: string; score: number }[];
  hit?: { fields: string[]; text: string; highlightStart: number; highlightEnd: number };
};
type Page = { items: Document[]; total: number; limit: number; offset: number; bodyUnavailableCount?: number; vectorUnavailableCount?: number };
type Upload = { key: string; file: File; state: 'waiting' | 'uploading' | 'saving' | 'done' | 'error';
  percent: number; message: string; retryable: boolean };
class ApiError extends Error {
  constructor(message: string, public retryable = false) { super(message); }
}
function errorFrom(body: unknown, fallback: string) {
  const data = body as { error?: { message?: string; retryable?: boolean }; detail?: unknown };
  const validation = Array.isArray(data?.detail) ? '请求参数无效，请核对输入后重试。' : fallback;
  return new ApiError(data?.error?.message ?? (typeof data?.detail === 'string' ? data.detail : validation),
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
function textStatus(value: string) { return ({ ready: '可正文搜索', failed: '正文提取失败', not_supported: '仅名称搜索', not_started: '正文待处理' } as Record<string, string>)[value] ?? value; }
function vectorStatus(value: string) { return ({ pending: '等待索引', processing: '索引处理中', ready: '可语义检索', failed: '索引失败', not_supported: 'PDF 暂不支持语义检索', not_started: '等待索引' } as Record<string, string>)[value] ?? value; }
function Hit({ hit }: { hit: NonNullable<Document['hit']> }) {
  const chars = Array.from(hit.text);
  return <p className="hit-snippet"><span>{hit.fields.includes('body') ? '正文命中' : '名称命中'}</span> {chars.slice(0, hit.highlightStart).join('')}<mark>{chars.slice(hit.highlightStart, hit.highlightEnd).join('')}</mark>{chars.slice(hit.highlightEnd).join('')}</p>;
}
function message(error: unknown) {
  return error instanceof TypeError ? '无法连接服务器，请检查网络后重试。'
    : error instanceof Error ? error.message : '请求失败，请稍后重试';
}

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
  const [categories, setCategories] = useState<Categories>({ items: [], unclassified: { activeCount: 0, archivedCount: 0 } });
  const [categoryError, setCategoryError] = useState('');
  const [categoryLoading, setCategoryLoading] = useState(true);
  const [categoryFilter, setCategoryFilter] = useState(() => new URLSearchParams(window.location.search).get('category') ?? '');
  const [archivedView, setArchivedView] = useState(() => new URLSearchParams(window.location.search).get('archived') === 'true');
  const [query, setQuery] = useState(() => new URLSearchParams(window.location.search).get('q') ?? '');
  const [searchMode, setSearchMode] = useState(() => new URLSearchParams(window.location.search).get('mode') === 'semantic' ? 'semantic' : 'keyword');
  const [indexBusy, setIndexBusy] = useState(false);
  const [keyword, setKeyword] = useState(query);
  const [keywordError, setKeywordError] = useState('');
  const [textBusy, setTextBusy] = useState(false);
  const textLock = useRef(false);
  const [newCategoryName, setNewCategoryName] = useState('');
  const [renameId, setRenameId] = useState('');
  const [renameName, setRenameName] = useState('');
  const [categoryBusy, setCategoryBusy] = useState(false);
  const [categoryMessage, setCategoryMessage] = useState('');
  const categoryLock = useRef(false);
  const [moveCategory, setMoveCategory] = useState('');
  const [actionBusy, setActionBusy] = useState(false);
  const actionLock = useRef(false);
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
  async function loadCategories() {
    setCategoryLoading(true); setCategoryError('');
    try { setCategories(await json<Categories>('/api/v1/categories')); }
    catch (error) { setCategoryError(message(error)); }
    finally { setCategoryLoading(false); }
  }
  async function refresh(offset = 0) {
    const generation = ++listRequest.current;
    setLoading(true); setListError('');
    try {
      const parameters = new URLSearchParams({ limit: '25', offset: String(offset), archived: String(archivedView) });
      if (categoryFilter) parameters.set('category_id', categoryFilter);
      if (query) parameters.set('q', query);
      const result = await json<Page>(`${query ? `/api/v1/search/${searchMode}` : '/api/v1/documents'}?${parameters}`);
      if (generation === listRequest.current) setPage(result);
    } catch (error) { if (generation === listRequest.current) setListError(message(error)); }
    finally { if (generation === listRequest.current) setLoading(false); }
  }
  useEffect(() => {
    void loadConfig(); void loadCategories();
    json<Health>('/api/v1/health').then(setHealth).catch(() => setHealth(null));
  }, []);
  useEffect(() => {
    const url = new URL(window.location.href);
    if (categoryFilter) url.searchParams.set('category', categoryFilter); else url.searchParams.delete('category');
    if (archivedView) url.searchParams.set('archived', 'true'); else url.searchParams.delete('archived');
    if (query) url.searchParams.set('q', query); else url.searchParams.delete('q');
    if (searchMode === 'semantic') url.searchParams.set('mode', 'semantic'); else url.searchParams.delete('mode');
    window.history.replaceState(null, '', url);
    detailRequest.current++; setDetail(null); setDetailError(''); setDetailLoading(false);
    setPage({ items: [], total: 0, limit: 25, offset: 0 });
    void refresh(0);
  }, [categoryFilter, archivedView, query, searchMode]);
  useEffect(() => {
    const queued = (row: Document) => ['pending', 'processing', 'not_started'].includes(row.vectorStatus);
    if (!page.items.some(queued) && !(detail && queued(detail))) return;
    const timer = window.setInterval(() => {
      if (detail) {
        json<Document>(`/api/v1/documents/${detail.id}`).then(saved => {
          setDetail(current => current?.id === saved.id ? { ...current, vectorStatus: saved.vectorStatus,
            vectorError: saved.vectorError, chunkCount: saved.chunkCount, textStatus: saved.textStatus,
            textError: saved.textError, textEncoding: saved.textEncoding } : current);
        }).catch(() => {});
      }
      void refresh(page.offset);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [page, detail, categoryFilter, archivedView, query, searchMode]);
  async function retryIndex(document: Document) {
    if (indexBusy) return;
    setIndexBusy(true);
    try {
      const saved = await json<Document>(`/api/v1/documents/${document.id}/index/retry`, { method: 'POST' });
      setDetail(current => current?.id === saved.id ? saved : current);
      setNotice('索引任务已提交，处理状态会自动更新；原文件仍可下载。');
      await refresh(page.offset);
    } catch (error) { setNotice(message(error)); }
    finally { setIndexBusy(false); }
  }
  function search(event: React.FormEvent) {
    event.preventDefault(); setKeywordError('');
    const term = keyword.trim();
    if (!term || term.length > 200 || /[\x00-\x1f\x7f]/.test(term)) { setKeywordError('请输入 1–200 字的关键词或问题。'); return; }
    if (term === query) void refresh(0); else setQuery(term);
  }
  async function retryText(document: Document) {
    if (textLock.current) return;
    textLock.current = true; setTextBusy(true); setNotice('');
    try {
      const saved = await json<Document>(`/api/v1/documents/${document.id}/text/retry`, { method: 'POST' });
      setDetail(current => current?.id === saved.id ? saved : current);
      setNotice(saved.textStatus === 'ready' ? '正文提取完成，可使用正文关键词搜索。' : saved.textError ?? '正文尚未就绪；原文件仍可下载。');
      await refresh(page.offset);
    } catch (error) { setNotice(message(error)); }
    finally { textLock.current = false; setTextBusy(false); }
  }
  async function saveCategory(renaming: boolean) {
    if (categoryLock.current) return;
    const name = (renaming ? renameName : newCategoryName).trim();
    if (!name || name.length > 80) { setCategoryMessage('分类名称不能为空且最多为 80 字。'); return; }
    if (renaming && !renameId) { setCategoryMessage('请先选择要修改的分类。'); return; }
    categoryLock.current = true; setCategoryBusy(true); setCategoryMessage('');
    try {
      const saved = await json<Category>(renaming ? `/api/v1/categories/${renameId}` : '/api/v1/categories', {
        method: renaming ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }),
      });
      if (!renaming) setNewCategoryName('');
      else setRenameName(saved.name);
      setCategoryMessage(`已${renaming ? '修改' : '创建'}分类「${saved.name}」。`);
      await loadCategories(); await refresh(page.offset);
      if (detail) await openDetail(detail.id);
    } catch (error) { setCategoryMessage(message(error)); }
    finally { categoryLock.current = false; setCategoryBusy(false); }
  }
  async function organize(document: Document, action: 'category' | 'archive' | 'restore') {
    if (actionLock.current) return;
    actionLock.current = true; setActionBusy(true); setNotice('');
    try {
      const saved = await json<Document>(`/api/v1/documents/${document.id}/${action}`, {
        method: action === 'category' ? 'PATCH' : 'POST',
        ...(action === 'category' ? { headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ categoryId: moveCategory || null }) } : {}),
      });
      setDetail(current => current?.id === saved.id ? saved : current);
      setNotice(action === 'category' ? `已将「${saved.name}」移至「${saved.category?.name ?? '未分类'}」。`
        : action === 'archive' ? `已归档「${saved.name}」，可在归档区找到并恢复。` : `已恢复「${saved.name}」，可在文件库找到。`);
      await loadCategories(); await refresh(0);
    } catch (error) { setNotice(message(error)); }
    finally { actionLock.current = false; setActionBusy(false); }
  }
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
          const saved = await sendFile(row.file, percent => changeUpload(row.key, { percent,
            state: percent === 100 ? 'saving' : 'uploading' }));
          successes++;
          changeUpload(row.key, { state: 'done', percent: 100, message: saved.textStatus === 'failed' ? '已保存，可下载；正文提取失败，请查看详情。' : '已保存，可下载' });
        } catch (error) {
          changeUpload(row.key, { state: 'error', message: message(error),
            retryable: error instanceof ApiError && error.retryable });
        }
      }
      if (successes) setNotice(`已保存 ${successes} 个文件。`);
      await loadCategories();
      if (successes && (categoryFilter || archivedView || query)) { setCategoryFilter(''); setArchivedView(false); setQuery(''); setKeyword(''); }
      else await refresh(0);
    } finally { uploadLock.current = false; setUploading(false); }
  }
  async function openDetail(id: string) {
    const generation = ++detailRequest.current;
    setDetail(null); setDetailError(''); setDetailLoading(true);
    try {
      const result = await json<Document>(`/api/v1/documents/${id}`);
      if (generation === detailRequest.current) { setDetail(result); setMoveCategory(result.category?.id ?? ''); }
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
    <details className="category-manager"><summary>管理分类 <span className="count">{categories.items.length}</span></summary>
      <div className="category-forms"><form onSubmit={event => { event.preventDefault(); void saveCategory(false); }}><label htmlFor="new-category">新分类名称</label><div><input id="new-category" maxLength={80} value={newCategoryName} disabled={categoryBusy} onChange={event => setNewCategoryName(event.target.value)} placeholder="例如：工程规范"/><button disabled={categoryBusy}>创建分类</button></div></form>
        <form onSubmit={event => { event.preventDefault(); void saveCategory(true); }}><label htmlFor="rename-category">要修改的分类</label><select id="rename-category" value={renameId} disabled={categoryBusy || categoryLoading} onChange={event => { setRenameId(event.target.value); setRenameName(categories.items.find(row => row.id === event.target.value)?.name ?? ''); }}><option value="">请选择分类</option>{categories.items.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select><label htmlFor="rename-name">修改后的名称</label><div><input id="rename-name" maxLength={80} value={renameName} disabled={categoryBusy || !renameId} onChange={event => setRenameName(event.target.value)}/><button disabled={categoryBusy || !renameId}>保存名称</button></div></form></div>
      {categoryMessage && <p role="status">{categoryMessage}</p>}
    </details>
    {categoryError && <div className="error notice" role="alert">分类读取失败：{categoryError}<button className="text-button" onClick={() => void loadCategories()}>重试读取分类</button></div>}
    <section className="keyword-search" aria-label="知识检索"><label htmlFor="search-mode">检索方式</label><select id="search-mode" value={searchMode} onChange={event => setSearchMode(event.target.value)}><option value="keyword">关键词搜索</option><option value="semantic">语义搜索</option></select><form onSubmit={search}><label htmlFor="keyword-input">{searchMode === 'semantic' ? '用自然语言描述你要找的内容' : '关键词搜索'}</label><div><input id="keyword-input" maxLength={200} value={keyword} onChange={event => setKeyword(event.target.value)} placeholder={searchMode === 'semantic' ? '例如：交给同事审阅代码前需要完成哪些检查？' : '文件名称、正文关键词或完整编号，例如 ENG-014'}/><button disabled={loading}>搜索</button><button className="secondary" type="button" disabled={!query && !keyword} onClick={() => { setKeyword(''); setQuery(''); setKeywordError(''); }}>清除搜索</button></div></form><p>{searchMode === 'semantic' ? '根据 TXT / Markdown 正文向量查找相关文件，展示来源片段；相似度不是正确概率。' : '搜索文件名称及 TXT / Markdown 正文；PDF 仅搜索名称。'}可结合下方分类筛选。</p>{keywordError && <p className="error" role="alert">{keywordError}</p>}</section>
    <div className="view-controls"><div className="view-tabs"><button className={!archivedView ? 'active' : ''} aria-pressed={!archivedView} onClick={() => setArchivedView(false)}>文件库</button><button className={archivedView ? 'active' : ''} aria-pressed={archivedView} onClick={() => setArchivedView(true)}>归档区</button></div><label>分类筛选 <select aria-label="分类筛选" value={categoryFilter} disabled={categoryLoading} onChange={event => setCategoryFilter(event.target.value)}><option value="">全部分类</option><option value="unclassified">未分类 · {archivedView ? categories.unclassified.archivedCount : categories.unclassified.activeCount}</option>{categories.items.map(row => <option key={row.id} value={row.id}>{row.name} · {archivedView ? row.archivedCount : row.activeCount}</option>)}</select></label></div>
    <div className="library-layout"><section className="library" aria-labelledby="library-title">
      <div className="section-heading"><div><h2 id="library-title">{query ? '搜索结果' : archivedView ? '归档文件' : categoryFilter === 'unclassified' ? '未分类文件' : categoryFilter ? categories.items.find(row => row.id === categoryFilter)?.name ?? '分类文件' : '全部文件'} <span className="count">{page.total}</span></h2><small>{query ? `${searchMode === 'semantic' ? '问题' : '关键词'}「${query}」 · ${archivedView ? '仅归档资料' : '已归档资料不在此显示'}` : archivedView ? '归档资料仍可下载，也可恢复至文件库' : '按上传时间排列 · 已归档资料不在此显示'}</small></div><button className="secondary" disabled={loading} onClick={() => { void refresh(page.offset); void loadCategories(); }}>刷新列表</button></div>
      {!!query && !!page.bodyUnavailableCount && <p className="search-warning" role="status">当前范围有 {page.bodyUnavailableCount} 份文件正文未就绪，仍可按名称查找和下载；详情中可重试正文提取。</p>}
      {!!query && !!page.vectorUnavailableCount && <p className="search-warning" role="status">当前范围有 {page.vectorUnavailableCount} 份文本索引尚未就绪，不参与语义结果；详情可查看状态、下载或重试。</p>}
      {listError && <div className="error notice" role="alert">{listError}<button className="text-button" onClick={() => void refresh(page.offset)}>重试</button></div>}
      {loading ? <div className="empty" role="status">{query ? '正在搜索…' : '正在加载文件…'}</div> : listError && page.items.length === 0 ? <div className="empty">暂时无法显示文件，请重试。</div> : page.items.length === 0 ? <div className="empty"><span className="empty-icon">{query ? '⌕' : archivedView ? '◇' : '＋'}</span><h3>{query ? '没有找到匹配的文件' : archivedView ? '没有符合筛选的归档文件' : categoryFilter ? '该分类还没有文件' : '这里还没有文件'}</h3><p>{query ? '请尝试其他关键词、完整编号或切换分类。' : archivedView ? '归档的文件会出现在这里，可随时恢复。' : categoryFilter ? '切换分类，或在文件详情中调整归属。' : '选择上方的文件，开始保存第一份资料。'}</p></div> : <div className="table-wrap"><table><thead><tr><th>名称 / 命中内容</th><th>分类</th><th>大小 / 上传时间</th><th>操作</th></tr></thead><tbody>{page.items.map(row => <tr key={row.id} className={detail?.id === row.id ? 'selected' : ''}>
        <td><div className="file-name"><span className={`file-badge ${row.extension}`}>{row.extension === 'markdown' ? 'MD' : row.extension.toUpperCase()}</span><button className="name-button" title={row.name} onClick={() => void openDetail(row.id)}>{row.name}</button></div>{row.hit && <Hit hit={row.hit}/>}{row.sources?.map(source => <blockquote className="source-snippet" key={source.ordinal}><small>{source.heading} · 片段 #{source.ordinal + 1} · 相似度 {source.score.toFixed(3)}</small><p>{source.text}</p></blockquote>)}<small className={row.vectorStatus === 'failed' ? 'error' : 'index-state'}>{vectorStatus(row.vectorStatus)}</small> {row.textStatus === 'failed' && <small className="error">正文提取失败 · 原文件可下载</small>}</td>
        <td><span className="category" title={row.category?.name ?? '未分类'}>{row.category?.name ?? '未分类'}</span></td><td><span>{size(row.sizeBytes)}</span><small>{date(row.uploadedAt)}</small></td>
        <td><button className="text-button" aria-label={`下载 ${row.name}`} disabled={!!downloadId} onClick={() => void download(row)}>{downloadId === row.id ? '下载中…' : '下载'}</button><button className="text-button archive-button" disabled={actionBusy} aria-label={`${row.archivedAt ? '恢复' : '归档'} ${row.name}`} onClick={() => void organize(row, row.archivedAt ? 'restore' : 'archive')}>{row.archivedAt ? '恢复' : '归档'}</button></td>
      </tr>)}</tbody></table></div>}
      {page.total > 25 && <div className="pagination"><button className="secondary" disabled={loading || page.offset === 0} onClick={() => void refresh(Math.max(0, page.offset - 25))}>上一页</button><span>{Math.floor(page.offset / 25) + 1} / {Math.ceil(page.total / 25)}</span><button className="secondary" disabled={loading || page.offset + 25 >= page.total} onClick={() => void refresh(page.offset + 25)}>下一页</button></div>}
    </section>
    <aside className="detail" aria-labelledby="detail-title"><span className="label">资料信息</span><h2 id="detail-title">文件详情</h2>
      {detailLoading ? <p role="status">正在加载详情…</p> : detailError ? <p className="error" role="alert">{detailError}</p> : detail ? <><h3 className="detail-name">{detail.name}</h3><dl>
        <dt>文件类型</dt><dd>{detail.extension.toUpperCase()}</dd><dt>分类</dt><dd>{detail.category?.name ?? '未分类'}</dd><dt>状态</dt><dd>{detail.archivedAt ? `已归档 · ${date(detail.archivedAt)}` : '文件库'}</dd><dt>正文检索</dt><dd>{textStatus(detail.textStatus)}{detail.textEncoding && <small>{detail.textEncoding}</small>}</dd><dt>语义索引</dt><dd>{vectorStatus(detail.vectorStatus)}{detail.vectorStatus === 'ready' && <small>{detail.chunkCount} 个片段</small>}</dd><dt>大小</dt><dd>{size(detail.sizeBytes)} <small>{detail.sizeBytes.toLocaleString()} 字节</small></dd><dt>上传时间</dt><dd>{date(detail.uploadedAt)}</dd><dt>SHA-256</dt><dd className="hash">{detail.sha256}</dd></dl>{detail.vectorError && <p className="error" role="alert">{detail.vectorError} 原文件仍可下载。</p>}{!['not_supported', 'pending', 'processing'].includes(detail.vectorStatus) && <button className="secondary" disabled={indexBusy} onClick={() => void retryIndex(detail)}>{indexBusy ? '正在提交…' : detail.vectorStatus === 'ready' ? '重新建立索引' : '重试索引'}</button>}{detail.textError && <p className="error" role="alert">{detail.textError}</p>}{['failed', 'not_started'].includes(detail.textStatus) && <button className="secondary" disabled={textBusy} onClick={() => void retryText(detail)}>{textBusy ? '正在提取正文…' : '重试正文提取'}</button>}<label className="move-label" htmlFor="move-category">调整文件归属</label><select id="move-category" value={moveCategory} disabled={actionBusy || categoryLoading || !!categoryError} onChange={event => setMoveCategory(event.target.value)}><option value="">未分类</option>{categories.items.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select><button className="secondary" disabled={actionBusy || categoryLoading || !!categoryError || moveCategory === (detail.category?.id ?? '')} onClick={() => void organize(detail, 'category')}>移动文件</button><p className="saved-note">{detail.archivedAt ? '归档保留原文件，可随时恢复和下载。' : '原文件已保存，可下载。'}</p><button disabled={!!downloadId} onClick={() => void download(detail)}>{downloadId === detail.id ? '下载中…' : '下载原文件'}</button><button className="secondary" disabled={actionBusy} onClick={() => void organize(detail, detail.archivedAt ? 'restore' : 'archive')}>{actionBusy ? '正在保存…' : detail.archivedAt ? '恢复文件' : '归档文件'}</button></> : <p className="detail-placeholder">点击文件名称，查看详情、调整分类或归档。</p>}
    </aside></div>
    <details className="diagnostics"><summary>服务状态 <span className={`dot ${health?.database.status === 'ready' ? 'ok' : ''}`}/></summary><div><p>数据库：{health?.database.status ?? '未能确认'} · 本地模型：{health?.model.status ?? '未能确认'} · 验证记录：{health?.database.probeCount ?? '—'}</p><button className="secondary" disabled={probeBusy} onClick={() => void probe()}>{probeBusy ? '正在核对…' : '验证数据库读写'}</button><p role="status">{probeMessage}</p></div></details>
    <footer>知识文件库 · 原文件保存在持久化存储中</footer>
  </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
