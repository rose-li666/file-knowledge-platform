"""One category/archive chain over real HTTP, only in an isolated test container."""
import argparse
import json
import os
import time
import urllib.parse
from pathlib import Path

from utf8_logs import configure_utf8_io
from verify_m2 import TcpClient
from verify_m5 import api, download_equal, upload, wait_document


def verify(client, report):
    assert os.environ.get('ACCEPTANCE_TEST_RUN'), 'Use run_acceptance_docker.py; do not target the demo service'
    assert api(client,'GET','/api/v1/documents')['total'] == 0, 'Test service must start empty'
    assert not api(client,'GET','/api/v1/categories')['items']
    raw='设备借用流程\n\n设备故障时停止使用，记录现象和发现时间，联系设备管理员，不要自行拆机。管理员安排维修或替代设备。'.encode('utf-8')
    row=upload(client,'分类归档链路.txt',raw)
    row=wait_document(client,row['id'],'ready')
    created=api(client,'POST','/api/v1/categories',{'name':'验收分类'},201)
    second=api(client,'POST','/api/v1/categories',{'name':'其他分类'},201)
    renamed=api(client,'PATCH',f'/api/v1/categories/{created["id"]}',{'name':'验收分类-已改名'})
    assert renamed['id'] == created['id'] and renamed['name'] == '验收分类-已改名'
    api(client,'PATCH',f'/api/v1/documents/{row["id"]}/category',{'categoryId':created['id']})
    def ids(kind,category=None,archived=False):
        params={'archived':str(archived).lower(),'limit':25}
        if category:params['category_id']=category
        path='/api/v1/documents'
        if kind != 'list':
            path='/api/v1/search/'+kind
            params['q']='设备故障' if kind == 'keyword' else '借用的器材坏了需要怎样处理？'
        response=api(client,'GET',path+'?'+urllib.parse.urlencode(params))
        report['observations'].append({'kind':kind,'category':category,'archived':archived,'response':response})
        return {r['id'] for r in response['items']}
    for kind in ('list','keyword','semantic'):
        assert ids(kind,created['id']) == {row['id']} and not ids(kind,second['id'])
    # Separate HTTP reads model page refresh: metadata must be durable, not local state.
    detail=api(client,'GET',f'/api/v1/documents/{row["id"]}')
    assert detail['category'] == {'id':created['id'],'name':'验收分类-已改名'}
    counts=api(client,'GET','/api/v1/categories')
    assert next(c for c in counts['items'] if c['id'] == created['id'])['activeCount'] == 1
    report['checks'].append({'check':'create_rename_move_filter_refresh_current_category_all_search_modes','passed':True})
    api(client,'PATCH',f'/api/v1/documents/{row["id"]}/category',{'categoryId':second['id']})
    for kind in ('list','keyword','semantic'):
        assert not ids(kind,created['id']) and ids(kind,second['id']) == {row['id']}
    report['checks'].append({'check':'moving_category_changes_keyword_and_semantic_immediately','passed':True})
    api(client,'POST',f'/api/v1/documents/{row["id"]}/archive')
    for kind in ('list','keyword','semantic'):
        assert not ids(kind) and not ids(kind,second['id'])
        assert ids(kind,second['id'],True) == {row['id']}
    archived=api(client,'GET',f'/api/v1/documents/{row["id"]}')
    assert archived['archivedAt']
    report['checks'].append({'check':'archive_excluded_default_list_keyword_semantic_found_archive','passed':True,
                             **download_equal(client,archived,raw)})
    restored=api(client,'POST',f'/api/v1/documents/{row["id"]}/restore')
    for kind in ('list','keyword','semantic'):
        assert ids(kind,second['id']) == {row['id']} and not ids(kind,second['id'],True)
    report['checks'].append({'check':'restore_reappears_list_keyword_semantic_download_sha_equal','passed':True,
                             **download_equal(client,restored,raw)})


def main():
    configure_utf8_io();parser=argparse.ArgumentParser()
    parser.add_argument('--report',type=Path,required=True);args=parser.parse_args()
    result={'checks':[],'observations':[],'failure':None,'type':'automated Docker real TCP HTTP'}
    started=time.perf_counter()
    try:verify(TcpClient('http://127.0.0.1:8000'),result)
    except Exception as error:
        import traceback
        traceback.print_exc();result['failure']=repr(error)
    result['seconds']=round(time.perf_counter()-started,3)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checks':len(result['checks']),'seconds':result['seconds'],'failure':result['failure']},ensure_ascii=False))
    if result['failure']:raise SystemExit(1)


if __name__ == '__main__':main()
