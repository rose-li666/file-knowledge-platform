import { useEffect, useRef, useState } from 'react';

export type OrganizableFile = { id: string; name: string; category: { id: string; name: string } | null; archivedAt: string | null };
type Category = { id: string; name: string };
type Result = { succeededCount: number; failedCount: number; items: {
  documentId: string; name: string | null; success: boolean; error?: { message: string; retryable: boolean }
}[] };
type Page = { items: OrganizableFile[]; total: number; offset: number; limit: number };
type Props = { open: boolean; target: Category | null; categories: Category[]; initialFiles: OrganizableFile[];
  onClose: () => void; onMoved: (ids: string[]) => Promise<void> };
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body?.error?.message ?? '操作失败，请核对后重试。');
  return body;
}

export function FileOrganizerDialog({ open, target, categories, initialFiles, onClose, onMoved }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const lock = useRef(false);
  const generation = useRef(0);
  const [selected, setSelected] = useState<Map<string, OrganizableFile>>(new Map());
  const [targetId, setTargetId] = useState('pick');
  const [name, setName] = useState('');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('');
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [page, setPage] = useState<Page>({ items: [], total: 0, limit: 20, offset: 0 });
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const adding = !!target;
  const targetName = target?.name ?? (targetId === 'unclassified' ? '未分类' : categories.find(c => c.id === targetId)?.name);
  const retryOnly = !!result?.failedCount && [...selected.keys()].every(id => result.items.some(item => item.documentId === id && !item.success));

  useEffect(() => {
    if (open) {
      setSelected(new Map(initialFiles.map(f => [f.id, f]))); setTargetId(target?.id ?? 'pick');
      setName(''); setQuery(''); setFilter(''); setOffset(0); setError(''); setResult(null); setLoadError('');
      setPage({ items: [], total: 0, limit: 20, offset: 0 }); setRevision(v => v + 1);
      if (!dialog.current?.open) dialog.current?.showModal();
    } else {
      generation.current++;
      if (dialog.current?.open) dialog.current.close();
    }
    // Reinitialize only on opening, preserving selection when category counts refresh.
  }, [open]);

  useEffect(() => {
    if (!open || !adding) return;
    const id = ++generation.current;
    const abort = new AbortController();
    setLoading(true); setLoadError('');
    const params = new URLSearchParams({ limit: '20', offset: String(offset), archived: 'false' });
    if (query) params.set('name_query', query);
    if (filter) params.set('category_id', filter);
    request<Page>('/api/v1/documents?' + params, { signal: abort.signal }).then(data => {
      if (generation.current === id) {
        if (offset && offset >= data.total) setOffset(data.total ? Math.floor((data.total - 1) / data.limit) * data.limit : 0);
        else setPage(data);
      }
    }).catch(failure => {
      if (!abort.signal.aborted && generation.current === id) setLoadError(failure instanceof Error ? failure.message : '文件列表读取失败。');
    }).finally(() => { if (generation.current === id) setLoading(false); });
    return () => abort.abort();
  }, [open, adding, query, filter, offset, revision]);

  function toggle(row: OrganizableFile) {
    if (lock.current) return;
    if (!selected.has(row.id) && selected.size >= 100) { setError('每次最多选择 100 个文件，请分批整理。'); return; }
    setSelected(current => {
      const next = new Map(current);
      if (next.has(row.id)) next.delete(row.id);
      else if (next.size < 100) next.set(row.id, row);
      return next;
    });
  }
  function close() { if (!lock.current) onClose(); }
  async function submit() {
    if (lock.current || !selected.size || targetId === 'pick') return;
    lock.current = true; setBusy(true); setError('');
    try {
      const saved = await request<Result>('/api/v1/documents/batch/category', { method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ categoryId: targetId === 'unclassified' ? null : targetId, documentIds: [...selected.keys()] }) });
      setResult(saved);
      const successful = saved.items.filter(item => item.success).map(item => item.documentId);
      setSelected(current => new Map([...current].filter(([id]) => !successful.includes(id))));
      await onMoved(successful);
      setRevision(v => v + 1);
    } catch (failure) {
      setError((failure instanceof TypeError ? '连接中断，结果尚未确认。' : failure instanceof Error ? failure.message : '移动结果尚未确认。')
        + ' 已保留选择；可刷新核对后再次提交，重复移入同一分类不会重复计数。');
    } finally { lock.current = false; setBusy(false); }
  }

  return <dialog ref={dialog} className="organizer-dialog" aria-labelledby="organizer-title"
    onCancel={event => { if (lock.current) event.preventDefault(); else close(); }} onClose={onClose}>
    <div className="organizer-frame">
      <header className="organizer-heading"><h2 id="organizer-title">{adding ? `添加文件到「${target.name}」` : '移动分类'}</h2></header>
      <div className="organizer-body">
        {!adding && <label className="organizer-target">目标分类<select aria-label="目标分类" value={targetId} disabled={busy}
          onChange={e => { setTargetId(e.target.value); setResult(null); }}>
          <option value="pick" disabled>请选择目标分类</option><option value="unclassified">未分类</option>
          {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select></label>}
        <p className="ownership-warning">每个文件只有一个主分类。“移入此分类”会改变所选文件的原归属，归档状态保持不变。</p>
        {result && <section className="batch-result" role="status"><p>已成功移入 {result.succeededCount} 个文件{result.failedCount ? `，${result.failedCount} 个失败，选择仅保留失败项。` : '。'}</p>
          {!!result.failedCount && <ul>{result.items.filter(item => !item.success).map(item => <li key={item.documentId}>
            {selected.get(item.documentId)?.name ?? item.name ?? item.documentId}（ID {item.documentId.slice(0, 8)}）：{item.error?.message}
          </li>)}</ul>}</section>}
        {error && <p className="error" role="alert">{error}</p>}
        {adding && <><form className="organizer-search" onSubmit={e => { e.preventDefault(); setQuery(name.trim()); setOffset(0); setRevision(v => v + 1); }}>
          <label>按文件名搜索<input aria-label="按文件名搜索" value={name} maxLength={200} disabled={busy} onChange={e => setName(e.target.value)} placeholder="例如：设备、DOC-238"/></label>
          <button disabled={busy}>查找文件</button>
        </form><label className="organizer-filter">现有分类<select aria-label="按现有分类筛选文件" value={filter} disabled={busy}
          onChange={e => { setFilter(e.target.value); setOffset(0); }}>
          <option value="">全部分类</option><option value="unclassified">未分类</option>
          {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select></label><small>从未归档文件中选择；选择在搜索、分类筛选和分页时保留。同名文件按 ID 区分。</small>
        {loading ? <p role="status">正在读取文件…</p> : loadError ? <p className="error" role="alert">{loadError} <button disabled={busy} onClick={() => setRevision(v => v + 1)}>重试读取</button></p>
          : !page.items.length ? <p>没有符合条件的文件，请调整搜索或分类。</p> : <div className="organizer-files">{page.items.map(row => <label className="organizer-file" key={row.id}>
            <input type="checkbox" aria-label={`选择文件 ${row.name} ID ${row.id.slice(0, 8)}`} checked={selected.has(row.id)} disabled={busy || (row.category?.id ?? 'unclassified') === targetId} onChange={() => toggle(row)}/>
            <span><strong>{row.name}</strong><small>当前分类：{row.category?.name ?? '未分类'} · ID {row.id.slice(0, 8)}{(row.category?.id ?? 'unclassified') === targetId ? ' · 已在此分类' : ''}</small></span>
          </label>)}</div>}
        {page.total > page.limit && <div className="organizer-pagination"><button className="secondary" disabled={busy || loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - page.limit))}>上一页文件</button>
          <span>{Math.floor(offset / page.limit) + 1} / {Math.ceil(page.total / page.limit)}</span>
          <button className="secondary" disabled={busy || loading || offset + page.limit >= page.total} onClick={() => setOffset(offset + page.limit)}>下一页文件</button></div>}</>}
        {!!selected.size && <details className="chosen-files" open={!adding}><summary>查看已选文件（{selected.size}）</summary>
          {[...selected.values()].map(row => <div key={row.id}><span>{row.name}<small>当前分类：{row.category?.name ?? '未分类'} · ID {row.id.slice(0, 8)}{row.archivedAt ? ' · 已归档' : ''}</small></span>
            <button className="text-button" disabled={busy} aria-label={`取消选择 ${row.name} ID ${row.id.slice(0, 8)}`} onClick={() => toggle(row)}>移除</button></div>)}
        </details>}
      </div>
      <footer className="organizer-actions"><p aria-live="polite">已选 {selected.size} 个{targetName ? ` · 目标：${targetName}` : ''}</p><div>
        <button className="secondary" disabled={busy} onClick={close}>{result && !selected.size ? '完成' : '取消'}</button>
        <button disabled={busy || !selected.size || targetId === 'pick'} onClick={() => void submit()}>{busy ? '正在移动…' : retryOnly ? '重试失败项' : '移入此分类'}</button>
      </div></footer>
    </div>
  </dialog>;
}
