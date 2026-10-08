"""Fresh-volume regression and exact metadata/vector checks after recreation."""
import argparse
import hashlib
import json
import sqlite3
import sys
import time
import urllib.parse
import uuid
import zipfile
from pathlib import Path

from utf8_logs import configure_utf8_io
from verify_m2 import TcpClient, multipart
from verify_m4 import verify as verify_keywords
from verify_m5 import QUERIES, api, download_equal, semantic, verify_fresh, wait_document


def snapshot(client, data_dir):
    documents = {}
    for archived in ('false','true'):
        offset = 0
        while True:
            page = api(client,'GET',f'/api/v1/documents?archived={archived}&limit=100&offset={offset}')
            documents.update({row['id']:row for row in page['items']})
            offset += len(page['items'])
            if offset >= page['total']: break
            assert page['items']
    with sqlite3.connect(data_dir/'db/platform.sqlite3') as db:
        vectors = {identity:hashlib.sha256(blob).hexdigest() for identity,blob in db.execute(
            "SELECT document_id || ':' || ordinal, embedding FROM chunks ORDER BY document_id,ordinal")}
        jobs = [list(row) for row in db.execute('SELECT document_id,generation,state,attempts FROM index_jobs ORDER BY document_id')]
    return {'documents':documents,'vectors':vectors,'jobs':jobs,'categories':api(client,'GET','/api/v1/categories')}


def prepare(client, fixture, data_dir, report):
    assert api(client,'GET','/api/v1/documents')['total'] == 0
    assert api(client,'GET','/api/v1/documents?archived=true')['total'] == 0
    assert api(client,'GET','/api/v1/categories')['items'] == []
    assert not semantic(client,'如何检查代码质量')['items']
    status,page,_ = client.request('GET','/')
    assert status == 200 and b'type="module"' in page
    report['checks'].append({'check':'new_empty_volume_0_files_0_categories_page_and_semantic_empty','passed':True})
    fresh={'uploads':[],'queries':[],'checks':[]}
    verify_fresh(client,fixture,fresh,data_dir)
    report['business']=fresh
    keywords={'checks':[],'queries':[],'original_files':[]}
    verify_keywords(client,fixture,keywords)
    report['keywords']=keywords
    wait_document(client,keywords['extraction_failure']['id'],'failed')
    category_id=fresh['categoryId']
    renamed=api(client,'PATCH',f'/api/v1/categories/{category_id}',{'name':'M6验收-规范'})
    assert renamed['name'] == 'M6验收-规范'
    api(client,'POST','/api/v1/categories',{'name':'ｍ６验收-规范'},409)
    api(client,'POST','/api/v1/categories',{'name':'   '},422)
    config=api(client,'GET','/api/v1/config')
    negatives=[('empty.txt',b'',400,'EMPTY_FILE'),('bad.exe',b'bad',415,'UNSUPPORTED_FILE_TYPE'),
               ('fake.pdf',b'text',415,'INVALID_PDF'),('../escape.txt',b'content',400,'INVALID_FILENAME'),
               ('large.txt',b'x'*(config['maxUploadBytes']+1),413,'FILE_TOO_LARGE')]
    for name,raw,expected,code in negatives:
        body,headers=multipart(name,raw)
        status,payload,_=client.request('POST','/api/v1/documents',body,headers)
        error=json.loads(payload)
        assert status == expected and error['error']['code'] == code,(name,status,error)
        report['checks'].append({'check':'upload_reject_'+code,'passed':True,'http':status})
    for path,expected in [('/api/v1/documents/'+str(uuid.uuid4()),404),('/api/v1/documents?limit=0',422),
            ('/api/v1/search/semantic?'+urllib.parse.urlencode({'q':'   '}),422),
            ('/api/v1/search/semantic?'+urllib.parse.urlencode({'q':'有效','category_id':str(uuid.uuid4())}),404)]:
        api(client,'GET',path,expected=expected)
    pdf=next(row for row in fresh['uploads'] if row['name'].endswith('.pdf'))
    api(client,'POST',f'/api/v1/documents/{pdf["id"]}/index/retry',expected=409)
    probe=api(client,'POST','/api/v1/m1/probes',{'value':'M6 fresh volume read/write'},201)
    assert api(client,'GET','/api/v1/m1/probes')['items'][0]['id'] == probe['id']
    report['checks'].append({'check':'category_rename_duplicate_validation_parameter_errors_and_database_rw','passed':True})
    # Preserve actual non-null archive values across BOTH restart and recreation.
    md=next(row for row in fresh['uploads'] if row['name'].startswith('01_'))
    for row in (pdf,md):
        api(client,'POST',f'/api/v1/documents/{row["id"]}/archive')
    report['archivedIds']=[pdf['id'],md['id']]
    state=snapshot(client,data_dir)
    assert all(state['documents'][identity]['archivedAt'] for identity in report['archivedIds'])
    assert all(job[2] not in ('pending','processing') for job in state['jobs'])
    report['snapshot']=state
    # The default frontend threshold also returns all five tested targets.
    for question,expected in QUERIES:
        params=urllib.parse.urlencode({'q':question,'category_id':category_id,'archived':str(expected==md['name']).lower()})
        default=api(client,'GET','/api/v1/search/semantic?'+params)
        assert any(hit['name'] == expected for hit in default['items'])
    report['checks'].append({'check':'all_5_targets_pass_default_0_45_threshold','passed':True})


def after(client, fixture, data_dir, before, report, restore=False):
    current=snapshot(client,data_dir)
    assert current == before['snapshot'],'Metadata, tasks or persisted vector bytes changed'
    report['checks'].append({'check':'all_ids_metadata_categories_non_null_archives_jobs_vectors_unchanged','passed':True,
                            'documents':len(current['documents']),'vectors':len(current['vectors'])})
    assert api(client,'GET','/api/v1/m1/probes')['items'][0]['value'] == 'M6 fresh volume read/write'
    with zipfile.ZipFile(fixture) as z:
        originals={Path(e.filename).name:z.read(e) for e in z.infolist() if not e.is_dir()}
    for row in before['business']['uploads']:
        download_equal(client,current['documents'][row['id']],originals[row['name']])
    for identity in before['archivedIds']:
        assert identity not in {r['id'] for r in api(client,'GET','/api/v1/documents?limit=100')['items']}
        assert identity in {r['id'] for r in api(client,'GET','/api/v1/documents?archived=true&limit=100')['items']}
    md=next(row for row in before['business']['uploads'] if row['name'].startswith('01_'))
    category_id=before['business']['categoryId']
    assert md['id'] not in {r['id'] for r in semantic(client,QUERIES[0][0],category_id)['items']}
    archived=semantic(client,QUERIES[0][0],category_id,True)
    assert archived['items'][0]['id'] == md['id']
    keyword=api(client,'GET','/api/v1/search/keyword?'+urllib.parse.urlencode({'q':'DOC-238','archived':'true','category_id':category_id}))
    assert keyword['items'][0]['id'] == md['id']
    report['checks'].append({'check':'restart_recreate_downloads_archive_keyword_and_semantic_still_work','passed':True})
    report['snapshot']=current
    if restore:
        for identity in before['archivedIds']:
            restored=api(client,'POST',f'/api/v1/documents/{identity}/restore')
            assert restored['archivedAt'] is None
            download_equal(client,restored,originals[restored['name']])
        assert semantic(client,QUERIES[0][0],category_id)['items'][0]['id'] == md['id']
        assert not api(client,'GET','/api/v1/documents?archived=true')['items']
        report['checks'].append({'check':'restore_after_recreate_then_download_and_semantic_search','passed':True})


def main():
    configure_utf8_io(); parser=argparse.ArgumentParser()
    parser.add_argument('--phase',choices=['prepare','after'],required=True)
    parser.add_argument('--zip',type=Path,required=True);parser.add_argument('--data-dir',type=Path,default=Path('/data'))
    parser.add_argument('--base-url',default='http://app:8000');parser.add_argument('--before',type=Path)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--restore',action='store_true');args=parser.parse_args()
    report={'checks':[],'failure':None,'phase':args.phase,'transport':'real Docker TCP HTTP','browser':'separate verification'}
    started=time.perf_counter()
    try:
        client=TcpClient(args.base_url)
        report['health']=api(client,'GET','/api/v1/health')
        if args.phase == 'prepare': prepare(client,args.zip,args.data_dir,report)
        else: after(client,args.zip,args.data_dir,json.loads(args.before.read_text('utf-8')),report,args.restore)
    except Exception as error:
        report['failure']=repr(error)
        import traceback
        traceback.print_exc()
    finally:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        report['seconds']=round(time.perf_counter()-started,3)
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'phase':args.phase,'checks':len(report['checks']),'failure':report['failure'],'seconds':report['seconds']},ensure_ascii=False),flush=True)
    if report['failure']: raise SystemExit(1)


if __name__ == '__main__': main()
