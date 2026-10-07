import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Health = {
  status: string; startupSeconds: number;
  database: { status: string; probeCount: number };
  model: { status: string; id: string; revision: string; dimension: number; loadSeconds: number | null };
};

function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [message, setMessage] = useState('正在检查服务…');
  const [busy, setBusy] = useState(false);
  async function refresh() {
    const response = await fetch('/api/v1/health');
    if (!response.ok) throw new Error('服务检查失败，请稍后重试');
    const result: Health = await response.json();
    setHealth(result);
    setMessage(result.status === 'ready' ? '基础环境已就绪' : '基础服务可用，模型尚未就绪');
  }
  useEffect(() => { refresh().catch((error: Error) => setMessage(error.message)); }, []);
  async function probe() {
    setBusy(true);
    try {
      const response = await fetch('/api/v1/m1/probes', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: `页面读写验证 ${new Date().toISOString()}` }),
      });
      if (!response.ok) throw new Error('数据库写入失败');
      const saved: { id: number; value: string } = await response.json();
      const read = await fetch('/api/v1/m1/probes');
      if (!read.ok) throw new Error('数据库读取失败');
      const rows: { items: { id: number; value: string }[] } = await read.json();
      if (!rows.items.some(row => row.id === saved.id && row.value === saved.value)) throw new Error('写入后未读到相同记录');
      await refresh();
      setMessage(`读写成功 · 记录 #${saved.id} 已保存并核对`);
    } catch (error) { setMessage(error instanceof Error ? error.message : '请求失败'); }
    finally { setBusy(false); }
  }
  return <main>
    <header><span className="mark">K</span><span>知识文件库</span><span className="stage">M1 · 基础验证</span></header>
    <section className="intro"><p className="eyebrow">文件管理与知识检索平台</p><h1>先让基础链路可靠运行。</h1><p>本阶段验证页面、数据库和本地中文向量模型。文件上传、分类与搜索界面将在后续阶段开放。</p></section>
    <div className="status" role="status" aria-live="polite"><span className={`dot ${health?.status === 'ready' ? 'ok' : ''}`}/>{message}</div>
    <section className="grid">
      <article><span className="label">数据库</span><h2>{health?.database.status === 'ready' ? '可读写' : '等待检查'}</h2><p>SQLite · 持久化目录</p><small>已保存验证记录：{health?.database.probeCount ?? '—'}</small><button disabled={busy} onClick={probe}>{busy ? '正在核对…' : '验证数据库读写'}</button></article>
      <article><span className="label">本地向量模型</span><h2>{health?.model.status === 'ready' ? '已加载' : health?.model.status === 'failed' ? '加载失败' : '等待检查'}</h2><p>BGE small · 中文 · CPU</p><small>{health?.model.dimension ?? 512} 维向量 · 加载 {health?.model.loadSeconds ?? '—'} 秒</small></article>
      <article><span className="label">资料验证</span><h2>5 组自然语言查询</h2><p>7 份 TXT / Markdown</p><small>真实排名、片段和耗时见 M1 实测报告；本页不宣称检索已通过。</small></article>
    </section>
    <footer><span>基础启动耗时：{health?.startupSeconds ?? '—'} 秒</span><button className="secondary" onClick={() => refresh().catch((error: Error) => setMessage(error.message))}>刷新状态</button></footer>
  </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
