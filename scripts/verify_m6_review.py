"""Review regression: concurrent text retry must fence the in-flight index."""
import argparse
import json
import sqlite3
import time
from pathlib import Path

from utf8_logs import configure_utf8_io
from verify_m5 import Server, api, download_equal, semantic, upload, wait_document


def verify(directory, model_dir, reports, result):
    raw='交付代码之前必须执行单元测试与静态检查，记录成功和失败情况。'.encode('utf-8')
    data=directory/'text-retry-race'
    server=Server(data,model_dir,'hold',reports)
    try:
        server.ready();row=upload(server.client,'M6正文重试竞态.md',raw)
        wait_document(server.client,row['id'],'processing')
        for _ in range(3):
            api(server.client,'POST',f'/api/v1/documents/{row["id"]}/index/retry',expected=202)
        with sqlite3.connect(data/'db/platform.sqlite3') as db:
            assert db.execute('SELECT generation,state,attempts FROM index_jobs').fetchone() == (1,'processing',1)
        retried=api(server.client,'POST',f'/api/v1/documents/{row["id"]}/text/retry')
        with sqlite3.connect(data/'db/platform.sqlite3') as db:
            generation,state=db.execute('SELECT generation,state FROM index_jobs').fetchone()
        result['raceObservation']={'generationAfterTextRetry':generation,'jobState':state,'document':retried}
        (data/'release-index').write_text('release',encoding='utf-8')
        assert generation == 2 and state == 'pending','Text retry did not invalidate the processing generation'
        ready=wait_document(server.client,row['id'],'ready')
        with sqlite3.connect(data/'db/platform.sqlite3') as db:
            count,minimum,maximum=db.execute('SELECT count(*),min(generation),max(generation) FROM chunks').fetchone()
            attempts=db.execute('SELECT attempts FROM index_jobs').fetchone()[0]
        assert count == ready['chunkCount'] and minimum == maximum == 2 and attempts == 2
        hit=semantic(server.client,'代码交付前应做哪些检查')['items'][0]
        assert hit['id'] == row['id'] and all(s['generation'] == 2 for s in hit['sources'])
        result['checks'].append({'check':'text_retry_fences_old_generation_actual_inference_and_unique_chunks',
                                'passed':True,'attempts':attempts,'generation':2,**download_equal(server.client,ready,raw)})
    finally: server.stop()
    data=directory/'missing-model'
    server=Server(data,directory/'nonexistent-model','normal',reports)
    try:
        health=server.ready(model=False)
        assert health['status'] == 'degraded' and health['model']['status'] == 'failed'
        row=upload(server.client,'M6模型缺失.txt',raw)
        failed=wait_document(server.client,row['id'],'failed')
        assert failed['textStatus'] == 'ready' and failed['vectorError']
        found=api(server.client,'GET','/api/v1/search/keyword?q=%E5%8D%95%E5%85%83%E6%B5%8B%E8%AF%95')
        assert found['items'][0]['id'] == row['id']
        error=api(server.client,'GET','/api/v1/search/semantic?q=%E6%A3%80%E6%9F%A5',expected=503)
        assert error['error']['code'] == 'MODEL_UNAVAILABLE'
        result['checks'].append({'check':'actual_missing_model_degraded_keyword_download_and_semantic_503',
                                'passed':True,'health':health,'error':error,**download_equal(server.client,failed,raw)})
    finally:server.stop()
    server=Server(data,model_dir,'normal',reports)
    try:
        server.ready()
        assert api(server.client,'GET',f'/api/v1/documents/{row["id"]}')['vectorStatus'] == 'failed'
        api(server.client,'POST',f'/api/v1/documents/{row["id"]}/index/retry',expected=202)
        wait_document(server.client,row['id'],'ready')
        assert semantic(server.client,'在提交代码以前如何验证质量')['items'][0]['id'] == row['id']
        result['checks'].append({'check':'real_model_restored_then_explicit_retry_and_source_query','passed':True})
    finally:server.stop()


def main():
    configure_utf8_io();p=argparse.ArgumentParser()
    p.add_argument('--data-dir',type=Path,required=True);p.add_argument('--model-dir',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True);args=p.parse_args()
    args.report.parent.mkdir(parents=True,exist_ok=True);args.data_dir.mkdir(parents=True,exist_ok=True)
    result={'checks':[],'failure':None,'transport':'real TCP HTTP isolated processes'};started=time.perf_counter()
    try:verify(args.data_dir,args.model_dir,args.report.parent,result)
    except Exception as error:
        result['failure']=repr(error)
        import traceback
        traceback.print_exc()
    finally:
        result['seconds']=round(time.perf_counter()-started,3)
        args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False),flush=True)
    if result['failure']:raise SystemExit(1)


if __name__ == '__main__':main()
