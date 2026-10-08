"""Predeclared corpus/supplement/synonym/negative cases against real new uploads."""
import argparse
import json
import os
import time
import urllib.parse
import zipfile
from pathlib import Path
from utf8_logs import configure_utf8_io
from verify_m2 import TcpClient
from verify_m5 import QUERIES, api, download_equal, upload, wait_document

FIXTURES=Path(__file__).resolve().parent/'fixtures'
SYNONYMS=[
    ('准备把代码交给评审的人时，哪些质量门槛必须满足？',QUERIES[0][1]),
    ('同一个文件因客户端重发到达服务两次，接口如何识别这是一笔操作？',QUERIES[1][1]),
    ('新版本正式交付前，怎么验证上传到查找和取回资料的流程？',QUERIES[2][1]),
    ('正文索引处理报错后，如何补处理旧资料而不让大家重新上传？',QUERIES[3][1]),
    ('容器换掉以后资料为什么消失，要检查什么才能防止再丢？',QUERIES[4][1]),
]
NEGATIVES=['土星的光环由什么构成？','早餐如何烤出松软面包？','该怎样给番茄苗施肥？']

def query(client,question,**options):
    return api(client,'GET','/api/v1/search/semantic?'+urllib.parse.urlencode({'q':question,**options}))

def verify(client,fixture,report):
    assert os.environ.get('ACCEPTANCE_TEST_RUN'),'Only run in independently created test container'
    assert api(client,'GET','/api/v1/documents')['total'] == 0,'Quality test requires empty data'
    assert not api(client,'GET','/api/v1/categories')['items'],'Quality test requires empty categories'
    core=api(client,'POST','/api/v1/categories',{'name':'检索评估-统一资料'},201)
    extra=api(client,'POST','/api/v1/categories',{'name':'检索评估-补充资料'},201)
    originals={}
    with zipfile.ZipFile(fixture) as archive:
        for e in archive.infolist():
            if e.is_dir():continue
            name=Path(e.filename).name;raw=archive.read(e)
            if Path(name).suffix.lower() not in {'.pdf','.txt','.md'}:continue
            row=upload(client,name,raw)
            api(client,'PATCH',f'/api/v1/documents/{row["id"]}/category',{'categoryId':core['id']})
            if not name.endswith('.pdf'):wait_document(client,row['id'],'ready')
            originals[name]=row
    supplement={}
    for name,path in [('上传测试_设备借用.txt','device-borrowing.txt'),('上传测试_会议行动项.md','meeting-actions.md')]:
        raw=(FIXTURES/path).read_bytes();row=upload(client,name,raw)
        api(client,'PATCH',f'/api/v1/documents/{row["id"]}/category',{'categoryId':extra['id']})
        wait_document(client,row['id'],'ready');supplement[name]=row
        report['downloads'].append({'name':name,**download_equal(client,row,raw)})
    report['categoryIds']={'core':core['id'],'extra':extra['id']}
    cases=[('original',q,name,core['id']) for q,name in QUERIES]
    cases += [('synonym',q,name,core['id']) for q,name in SYNONYMS]
    cases += [('new_upload','借来的设备坏了应该怎么办？','上传测试_设备借用.txt',None),
              ('new_upload_synonym','借用的器材发生故障，该向谁报告并怎样处理？','上传测试_设备借用.txt',None),
              ('new_upload','散会以后谁来负责下一步，怎样知道任务真正完成了？','上传测试_会议行动项.md',None)]
    for group,question,expected,category in cases:
        options={'category_id':category} if category else {}
        clock=time.perf_counter()
        before=query(client,question,score_window=1,source_window=1,limit=10,**options)
        after=query(client,question,**options)
        broad=query(client,question,score_window=1,limit=25,**options)
        names=[r['name'] for r in after['items']]
        rank=names.index(expected)+1 if expected in names else None
        old=[r['name'] for r in before['items']]
        entry={'group':group,'question':question,'expected':expected,
               'beforeRank':old.index(expected)+1 if expected in old else None,'afterRank':rank,
               'before':before,'after':after,'expanded':broad,'seconds':round(time.perf_counter()-clock,3)}
        report['queries'].append(entry)
        print(group,expected,'before',entry['beforeRank'],'after',rank,flush=True)
        assert rank,'Predeclared target missing'
        if group == 'original':assert rank and rank <= 3,'Original five target recall regressed'
        # The wider route must retain every original-floor eligible ID.
        assert {r['id'] for r in before['items']}.issubset({r['id'] for r in broad['items']})
        if group == 'new_upload' and expected == '上传测试_设备借用.txt':
            assert rank == 1 and not any('发布检查' in r['name'] for r in after['items'])
            assert after['items'][0]['sources'][0]['text'].startswith('发现投影仪')
    report['checks'].append({'check':'original_five_top3_retained_device_release_tail_removed_expansion_available','passed':True})
    for question in NEGATIVES:
        before=query(client,question,score_window=1,limit=10)
        after=query(client,question)
        report['negatives'].append({'question':question,'before':before,'after':after})
        assert not after['items'],('Negative query returned candidate',question,after)
    report['checks'].append({'check':'three_unrelated_queries_return_empty','passed':True})
    for cat,allowed in [(core,originals),(extra,supplement)]:
        result=query(client,'借来的设备坏了应该怎么办？',category_id=cat['id'],score_window=1)
        assert all(r['category']['id'] == cat['id'] for r in result['items'])
        report['filters'].append({'category':cat,'response':result})
    row=supplement['上传测试_设备借用.txt']
    api(client,'PATCH',f'/api/v1/documents/{row["id"]}/category',{'categoryId':core['id']})
    assert row['id'] not in {r['id'] for r in query(client,'借来的设备坏了应该怎么办？',category_id=extra['id'],score_window=1)['items']}
    api(client,'POST',f'/api/v1/documents/{row["id"]}/archive')
    assert row['id'] not in {r['id'] for r in query(client,'借来的设备坏了应该怎么办？',score_window=1)['items']}
    assert row['id'] in {r['id'] for r in query(client,'借来的设备坏了应该怎么办？',archived='true')['items']}
    api(client,'POST',f'/api/v1/documents/{row["id"]}/restore')
    assert row['id'] in {r['id'] for r in query(client,'借来的设备坏了应该怎么办？')['items']}
    report['checks'].append({'check':'current_category_archive_restore_filter_quality_queries','passed':True})
    twins=[]
    for _ in range(2):
        raw=(FIXTURES/'device-borrowing.txt').read_bytes()
        twin=upload(client,'同名设备资料.txt',raw);wait_document(client,twin['id'],'ready');twins.append(twin)
    assert twins[0]['id'] != twins[1]['id']
    hits=query(client,'借来的设备坏了应该怎么办？',score_window=1,limit=25)
    assert {r['id'] for r in twins}.issubset({r['id'] for r in hits['items']})
    assert all(r['uploadedAt'] and 'category' in r for r in hits['items'])
    report['checks'].append({'check':'same_name_separate_ids_category_upload_time_kept','passed':True,'ids':[r['id'] for r in twins]})

def main():
    configure_utf8_io();p=argparse.ArgumentParser()
    p.add_argument('--zip',type=Path,required=True);p.add_argument('--report',type=Path,required=True);args=p.parse_args()
    result={'queries':[],'negatives':[],'filters':[],'downloads':[],'checks':[],'failure':None,
            'transport':'isolated real Docker TCP HTTP, actual new model vectors',
            'beforePolicy':'min_score=.45, score_window=1, source_window=1, limit=10; same new-upload index',
            'afterPolicy':'min_score=.45 unchanged, score_window=.12, source_window=.08, limit=5'}
    started=time.perf_counter()
    try:verify(TcpClient('http://127.0.0.1:8000'),args.zip,result)
    except Exception as error:
        import traceback
        traceback.print_exc();result['failure']=repr(error)
    result['seconds']=round(time.perf_counter()-started,3)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checks':len(result['checks']),'seconds':result['seconds'],'failure':result['failure']},ensure_ascii=False))
    if result['failure']:raise SystemExit(1)

if __name__ == '__main__':main()
