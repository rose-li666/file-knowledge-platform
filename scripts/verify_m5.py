"""Fresh business uploads and actual HTTP, inference failure, process crash/recovery."""
import argparse
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import uuid
import zipfile
from pathlib import Path

from utf8_logs import configure_utf8_io
from verify_m2 import TcpClient, multipart

ROOT = Path(__file__).resolve().parents[1]

QUERIES = [
    ("交给同事审阅修改之前，应该怎样自查并描述测试结果？", "01_代码提交规范_v2.1.md"),
    ("网络断了又提交同一份上传请求，服务怎样防止保存两次？", "03_文件服务接口约定_v1.2.md"),
    ("上线刚启动，新版本要验证哪些用户操作才能放心交付？", "02_发布检查清单_v1.4.md"),
    ("文档上传成功却查不到正文，数据换了嵌套结构，怎么补救而不用重传？", "06_星桥项目_故障复盘_2026-09-21.md"),
    ("重建运行环境后以前的资料丢了，该怎样排查挂载和保住原有数据？", "09_本地部署故障排查_v1.3.txt"),
]


def api(client, method, path, body=None, expected=200):
    raw = json.dumps(body).encode() if body is not None else None
    status, payload, _ = client.request(method, path, raw, {"Content-Type": "application/json"} if body is not None else {})
    assert status == expected, (method, path, status, payload[:600])
    return json.loads(payload)


def upload(client, name, raw):
    body, headers = multipart(name, raw)
    status, response, _ = client.request("POST", "/api/v1/documents", body, headers)
    assert status == 201, (status, response[:600])
    return json.loads(response)


def wait_document(client, identity, wanted, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = api(client, "GET", f"/api/v1/documents/{identity}")
        if row["vectorStatus"] == wanted:
            return row
        if row["vectorStatus"] == "failed" and wanted != "failed":
            raise AssertionError(row)
        time.sleep(.2)
    raise AssertionError(("index state timeout", wanted, row))


def download_equal(client, row, raw):
    status, downloaded, _ = client.request("GET", row["downloadUrl"])
    assert status == 200 and raw == downloaded
    sha = hashlib.sha256(raw).hexdigest()
    assert row["sha256"] == sha
    return {"http": status, "originalSha256": sha, "downloadSha256": hashlib.sha256(downloaded).hexdigest()}


def semantic(client, question, category=None, archived=False):
    params = {"q": question, "limit": 25, "min_score": 0, "score_window": 1, "archived": str(archived).lower()}
    if category:
        params["category_id"] = category
    return api(client, "GET", "/api/v1/search/semantic?" + urllib.parse.urlencode(params))


def verify_fresh(client, fixture, report, data_dir=None):
    health = api(client, "GET", "/api/v1/health")
    assert health["milestone"] == "M5" and health["model"]["status"] == "ready", health
    report["health"] = health
    # Dedicated category ensures results refer only to this run's NEW upload IDs.
    suffix = uuid.uuid4().hex[:8]
    category = api(client, "POST", "/api/v1/categories", {"name": "M5新上传-" + suffix}, 201)
    empty = api(client, "POST", "/api/v1/categories", {"name": "M5空范围-" + suffix}, 201)
    rows, originals = {}, {}
    with zipfile.ZipFile(fixture) as archive:
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            name = Path(entry.filename).name
            if Path(name).suffix.lower() not in {".txt", ".md", ".pdf"}:
                continue
            raw = archive.read(entry)
            clock = time.perf_counter()
            saved = upload(client, name, raw)
            api(client, "PATCH", f'/api/v1/documents/{saved["id"]}/category', {"categoryId": category["id"]})
            row = saved if name.endswith('.pdf') else wait_document(client, saved["id"], "ready")
            assert row["textStatus"] == ("not_supported" if name.endswith('.pdf') else "ready"), row
            if name.endswith('.pdf'):
                assert row["vectorStatus"] == "not_supported"
            else:
                assert row["chunkCount"] > 0
            evidence = download_equal(client, row, raw)
            rows[name], originals[name] = row, raw
            report["uploads"].append({"id": row["id"], "name": name, "textStatus": row["textStatus"],
                "vectorStatus": row["vectorStatus"], "chunkCount": row["chunkCount"],
                "seconds": round(time.perf_counter()-clock, 3), **evidence})
            print("PASS new business upload " + name, flush=True)
    assert len(rows) == 10
    report["categoryId"] = category["id"]
    for question, expected in QUERIES:
        clock = time.perf_counter()
        result = semantic(client, question, category["id"])
        names = [hit["name"] for hit in result["items"]]
        rank = names.index(expected)+1
        for hit in result["items"]:
            assert hit["id"] == rows[hit["name"]]["id"]
            for source in hit["sources"]:
                assert source["text"] in originals[hit["name"]].decode('utf-8-sig').replace('\r\n','\n')
        report["queries"].append({"question": question, "expected": expected, "actualRank": rank,
            "targetInTop3": rank <= 3, "seconds": round(time.perf_counter()-clock, 3), "rankings": result["items"]})
        print(f"QUERY rank={rank} {expected}", flush=True)
    assert all(row["targetInTop3"] for row in report["queries"]), "Actual top3 targets failed; inspect rankings"
    row = rows[QUERIES[0][1]]
    path = f'/api/v1/documents/{row["id"]}'
    question = QUERIES[0][0]
    def ids(category_id, archived=False):
        return {r["id"] for r in semantic(client, question, category_id, archived)["items"]}
    assert not ids(empty["id"])
    api(client, "PATCH", path+"/category", {"categoryId": empty["id"]})
    assert row["id"] not in ids(category["id"]) and ids(empty["id"]) == {row["id"]}
    api(client, "POST", path+"/archive")
    assert not ids(empty["id"]) and ids(empty["id"], True) == {row["id"]}
    api(client, "POST", path+"/restore")
    assert ids(empty["id"]) == {row["id"]} and not ids(empty["id"], True)
    download_equal(client, row, originals[row["name"]])
    api(client, "PATCH", path+"/category", {"categoryId": category["id"]})
    report["checks"].append({"check": "live_category_archive_restore_filters_and_download", "passed": True})
    if data_dir:
        with sqlite3.connect(data_dir / 'db/platform.sqlite3') as database:
            persisted = []
            for row in rows.values():
                chunks = database.execute('SELECT ordinal,generation,length(embedding),text,model_revision FROM chunks WHERE document_id=? ORDER BY ordinal', (row["id"],)).fetchall()
                if row['extension'] != 'pdf':
                    assert len(chunks) == row['chunkCount'] and len(chunks) == len({c[0] for c in chunks})
                    assert all(c[2] == 512*4 for c in chunks)
                else:
                    assert not chunks
                persisted.append({"id": row['id'], "chunks": len(chunks), "embeddingBytes": sorted({c[2] for c in chunks})})
        report["checks"].append({"check": "independent_sqlite_persisted_512d_unique_chunks", "passed": True, "documents": persisted})
        first_count = row = rows[QUERIES[0][1]]
        api(client, "POST", f'/api/v1/documents/{row["id"]}/index/retry', expected=202)
        row = wait_document(client, row['id'], 'ready')
        assert row['chunkCount'] == first_count['chunkCount']
        with sqlite3.connect(data_dir / 'db/platform.sqlite3') as db:
            count, generations = db.execute('SELECT count(*),count(DISTINCT generation) FROM chunks WHERE document_id=?', (row['id'],)).fetchone()
            assert count == row['chunkCount'] and generations == 1
        report['checks'].append({"check": "reindex_replaces_chunks_without_duplicates", "passed": True, "count": count})


class Server:
    def __init__(self, directory, model_dir, mode, logs):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        self.client = TcpClient(f'http://127.0.0.1:{port}')
        environment = dict(os.environ, DATA_DIR=str(directory.resolve()), MODEL_DIR=str(model_dir.resolve()),
                           M5_TEST_MODE=mode, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        self.log = (logs / f'{directory.name}-{mode}-{uuid.uuid4().hex[:5]}.log').open('w', encoding='utf-8')
        self.command = [sys.executable, str(ROOT/'scripts/m5_fault_server.py'), str(port)]
        self.process = subprocess.Popen(self.command, cwd=ROOT, env=environment, stdout=self.log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    def ready(self, model=True):
        deadline = time.monotonic()+90
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AssertionError(('Server exited during startup', self.process.returncode, self.command))
            try:
                health = api(self.client, 'GET', '/api/v1/health')
                if model:
                    assert health['model']['status'] == 'ready', health
                return health
            except OSError:
                time.sleep(.2)
        raise AssertionError('Server startup timeout')
    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.log.close()


def faults(directory, model_dir, logs, report):
    raw = '项目交付之前需要编写单元测试，运行静态检查，描述验证结果。'.encode('utf-8')
    data = directory/'inference-failure'
    server = Server(data, model_dir, 'encode_failure', logs)
    try:
        server.ready()
        saved = upload(server.client, 'M5向量失败可下载.txt', raw)
        row = wait_document(server.client, saved['id'], 'failed')
        assert row['textStatus'] == 'ready' and row['vectorError']
        result = api(server.client, 'GET', '/api/v1/search/keyword?'+urllib.parse.urlencode({'q':'单元测试'}))
        assert result['items'][0]['id'] == row['id']
        hashes = download_equal(server.client, row, raw)
        semantic_result = semantic(server.client, '交付前要做什么检查')
        assert not semantic_result['items'] and semantic_result['vectorUnavailableCount'] == 1
        report['checks'].append({'check':'actual_inference_failure_text_search_and_download_still_work', 'passed':True, 'document':row, **hashes})
    finally:
        server.stop()
    server = Server(data, model_dir, 'normal', logs)
    try:
        server.ready()
        assert api(server.client,'GET',f'/api/v1/documents/{saved["id"]}')['vectorStatus'] == 'failed'
        api(server.client,'POST',f'/api/v1/documents/{saved["id"]}/index/retry',expected=202)
        row = wait_document(server.client,saved['id'],'ready')
        assert semantic(server.client,'怎样在交付前确保代码质量')['items'][0]['id'] == row['id']
        report['checks'].append({'check':'explicit_retry_after_failure_real_model_ready', 'passed':True, 'document':row})
    finally:
        server.stop()
    data = directory/'interrupted-job'
    server = Server(data, model_dir, 'worker_crash', logs)
    try:
        server.ready()
        try:
            saved = upload(server.client,'M5重启任务.md',raw)
        except OSError:
            saved = None
        exit_code = server.process.wait(timeout=30)
        assert exit_code == 75 and (data/'test-checkpoint').exists()
        with sqlite3.connect(data/'db/platform.sqlite3') as db:
            identity, generation, state = db.execute('SELECT document_id,generation,state FROM index_jobs').fetchone()
            assert state == 'processing' and db.execute('SELECT count(*) FROM chunks').fetchone()[0] == 0
        report['checks'].append({'check':'real_worker_process_crash_with_durable_processing_claim', 'passed':True, 'exitCode':exit_code, 'id':identity})
    finally:
        server.stop()
    server = Server(data,model_dir,'normal',logs)
    try:
        health=server.ready()
        assert health['indexing']['recovery']['requeued'] == 1
        row=wait_document(server.client,identity,'ready')
        assert semantic(server.client,'代码交付前怎么检查')['items'][0]['id'] == identity
        with sqlite3.connect(data/'db/platform.sqlite3') as db:
            count, gen_count = db.execute('SELECT count(*),count(DISTINCT generation) FROM chunks').fetchone()
            attempts = db.execute('SELECT attempts FROM index_jobs').fetchone()[0]
            assert count == row['chunkCount'] and gen_count == 1 and attempts == 2
        report['checks'].append({'check':'restart_recovers_claim_no_duplicate_chunks_real_query', 'passed':True, 'attempts':attempts, **download_equal(server.client,row,raw)})
    finally:
        server.stop()
    data=directory/'repeated-retry'
    server=Server(data,model_dir,'hold',logs)
    try:
        server.ready(); saved=upload(server.client,'M5单并发.md',raw)
        wait_document(server.client,saved['id'],'processing')
        for _ in range(3):
            api(server.client,'POST',f'/api/v1/documents/{saved["id"]}/index/retry',expected=202)
        with sqlite3.connect(data/'db/platform.sqlite3') as db:
            count, generation, attempts = db.execute('SELECT count(*),generation,attempts FROM index_jobs').fetchone()
            assert (count,generation,attempts) == (1,1,1)
        (data/'release-index').write_text('release',encoding='utf-8')
        wait_document(server.client,saved['id'],'ready')
        report['checks'].append({'check':'repeated_processing_retry_idempotent_one_job_one_generation', 'passed':True})
    finally:
        server.stop()
    data=directory/'landed-before-db'
    server=Server(data,model_dir,'landed_crash',logs)
    try:
        server.ready()
        try:
            upload(server.client,'M5已落盘未提交.txt',raw)
        except OSError:
            pass
        exit_code=server.process.wait(timeout=30)
        assert exit_code == 74
        with sqlite3.connect(data/'db/platform.sqlite3') as db:
            assert db.execute('SELECT count(*) FROM documents').fetchone()[0] == 0
        assert len(list((data/'uploads').glob('*.bin'))) == 1
        report['checks'].append({'check':'real_crash_after_formal_file_before_sql_commit', 'passed':True, 'exitCode':exit_code})
    finally:
        server.stop()
    server=Server(data,model_dir,'normal',logs)
    try:
        health=server.ready()
        assert len(health['uploadRecovery']['quarantined']) == 2
        assert api(server.client,'GET','/api/v1/documents')['total'] == 0
        assert not list((data/'uploads').glob('*.bin'))
        originals=[p for p in (data/'quarantine').iterdir() if p.name.endswith('.bin')]
        assert len(originals) == 1 and originals[0].read_bytes() == raw
        report['checks'].append({'check':'restart_quarantines_uncommitted_original_and_intent_without_data_loss', 'passed':True, 'recovery':health['uploadRecovery']})
    finally:
        server.stop()


def main():
    configure_utf8_io()
    parser=argparse.ArgumentParser()
    parser.add_argument('--zip',type=Path,required=True)
    parser.add_argument('--data-dir',type=Path,required=True)
    parser.add_argument('--model-dir',type=Path,default=Path(os.environ.get('MODEL_DIR',str(ROOT/'models/bge'))))
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--base-url')
    parser.add_argument('--skip-faults',action='store_true')
    parser.add_argument('--fault-dir',type=Path)
    args=parser.parse_args()
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.data_dir.mkdir(parents=True,exist_ok=True)
    report={'uploads':[],'queries':[],'checks':[],'failure':None,'browser':'not verified by this script',
            'transport':'real TCP HTTP','scope':'new business uploads; no M1 evaluation vector reuse'}
    started=time.perf_counter(); server=None
    try:
        if args.base_url:
            if not os.environ.get("ACCEPTANCE_TEST_RUN"):
                raise RuntimeError("External HTTP verification requires an isolated test runner marker")
            client=TcpClient(args.base_url)
        else:
            if (args.data_dir/'business/db/platform.sqlite3').exists():
                raise RuntimeError('Use a fresh verification directory to prove new uploads')
            server=Server(args.data_dir/'business',args.model_dir,'normal',args.report.parent)
            server.ready(); client=server.client
        data_dir=args.data_dir if args.base_url else args.data_dir/'business'
        verify_fresh(client,args.zip,report,data_dir)
        if server:
            server.stop(); server=None
            server=Server(data_dir,args.model_dir,'normal',args.report.parent)
            server.ready()
            assert semantic(server.client,QUERIES[0][0],report['categoryId'])['items']
            report['checks'].append({'check':'fresh_process_reloads_persisted_business_vectors', 'passed':True})
            server.stop(); server=None
        if not args.skip_faults:
            faults(args.fault_dir or args.data_dir/'isolated-faults',args.model_dir,args.report.parent,report)
    except Exception as error:
        report['failure']=repr(error)
        print('FAILED '+repr(error),flush=True)
        import traceback
        traceback.print_exc()
    finally:
        if server: server.stop()
        report['totalSeconds']=round(time.perf_counter()-started,3)
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Report: '+str(args.report.resolve()),flush=True)
    if report['failure']: raise SystemExit(1)
    print('M5 HTTP checks passed. Browser and M6 fresh-volume deployment remain separate.',flush=True)


if __name__ == '__main__':
    main()
