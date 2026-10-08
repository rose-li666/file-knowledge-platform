import { useEffect, useRef, useState } from 'react';

type Props = {
  open: boolean; categories: { id: string; name: string }[]; initialCategoryId: string;
  loading: boolean; onClose: () => void; onSave: (id: string | null, name: string) => Promise<void>;
};

export function CategoryManagerDialog({ open, categories, initialCategoryId, loading, onClose, onSave }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const saving = useRef(false);
  const [mode, setMode] = useState<'create' | 'rename'>('create');
  const [selectedId, setSelectedId] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const selected = categories.find(row => row.id === selectedId);

  useEffect(() => {
    if (open) {
      const current = categories.find(row => row.id === initialCategoryId);
      setMode(current ? 'rename' : 'create'); setSelectedId(current?.id ?? '');
      setName(current?.name ?? ''); setError('');
      if (!dialog.current?.open) dialog.current?.showModal();
      input.current?.focus(); input.current?.select();
    } else if (dialog.current?.open) dialog.current.close();
    // Initialize a draft when opened; refreshing categories must not erase typed input.
  }, [open]);

  function changeMode(next: 'create' | 'rename') {
    const current = categories.find(row => row.id === selectedId) ?? categories[0];
    setMode(next); setError('');
    setSelectedId(next === 'rename' ? current?.id ?? '' : '');
    setName(next === 'rename' ? current?.name ?? '' : '');
    input.current?.focus(); input.current?.select();
  }
  function close() { if (!saving.current) onClose(); }
  async function submit() {
    if (saving.current) return;
    const value = name.trim();
    if (!value || Array.from(value).length > 80) { setError('分类名称不能为空且最多为 80 字。'); input.current?.focus(); return; }
    if (mode === 'rename' && !selected) { setError('请选择要修改的分类。'); return; }
    saving.current = true; setBusy(true); setError('');
    try { await onSave(mode === 'rename' ? selectedId : null, value); onClose(); }
    catch (failure) {
      setError(failure instanceof TypeError ? '无法连接服务器，请稍后重试。'
        : failure instanceof Error ? failure.message : '保存失败，请稍后重试。');
    } finally { saving.current = false; setBusy(false); }
  }

  return <dialog ref={dialog} className="category-dialog" aria-labelledby="category-dialog-title"
    onCancel={event => { if (saving.current) event.preventDefault(); else close(); }} onClose={onClose}>
    <form className="category-dialog-form" onSubmit={event => { event.preventDefault(); void submit(); }}>
      <header className="category-dialog-heading"><h2 id="category-dialog-title">管理分类</h2><small>{categories.length} 个分类</small></header>
      <div className="category-dialog-modes" role="group" aria-label="分类管理方式">
        <button type="button" aria-pressed={mode === 'create'} disabled={busy} onClick={() => changeMode('create')}>创建分类</button>
        <button type="button" aria-pressed={mode === 'rename'} disabled={busy || loading || !categories.length} onClick={() => changeMode('rename')}>修改分类名称</button>
      </div>
      <div className="category-dialog-selection">
        {mode === 'rename' ? <><label htmlFor="rename-category">要修改的分类</label>
          <select id="rename-category" title={selected?.name} value={selectedId} disabled={busy || loading}
            onChange={event => { const row = categories.find(item => item.id === event.target.value);
              setSelectedId(row?.id ?? ''); setName(row?.name ?? ''); setError(''); }}>
            <option value="">请选择分类</option>{categories.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}
          </select><p className="selected-category-name">{selected?.name ?? '选择分类后会自动填入原名称。'}</p></>
          : <p>新分类保存后可在文件详情中调整文件归属。</p>}
      </div>
      <div className="category-dialog-editor">
        <label htmlFor="category-name">{mode === 'rename' ? '修改后的名称' : '新分类名称'}</label>
        <input ref={input} id="category-name" value={name} maxLength={80} required title={name}
          disabled={busy || (mode === 'rename' && !selected)} placeholder="例如：工程规范"
          onChange={event => setName(event.target.value)} aria-invalid={!!error} aria-describedby={error ? 'category-save-error' : undefined} />
        {error && <p id="category-save-error" className="error" role="alert">{error}</p>}
      </div>
      <footer className="category-dialog-actions">
        <button type="button" className="secondary" disabled={busy} onClick={close}>取消</button>
        <button type="submit" disabled={busy || (mode === 'rename' && !selected)}>{busy ? '正在保存…' : mode === 'rename' ? '保存名称' : '保存新分类'}</button>
      </footer>
    </form>
  </dialog>;
}
