"""Real HTTP batch/category contracts; use only an owned isolated test container."""
import argparse
import json
import os
import time
import urllib.parse
import uuid
from pathlib import Path
from utf8_logs import configure_utf8_io
from verify_m2 import TcpClient
from verify_m5 import api, upload, wait_document, download_equal


def verify(client, report):
    assert os.environ.get('ACCEPTANCE_TEST_RUN'), 'Requires isolated acceptance container marker'
    assert api(client, 'GET', '/api/v1/documents')['total'] == 1, 'Fresh P0 run required'
    source = api(client, 'POST', '/api/v1/categories', {'name': '批量来源'}, 201)
    target = api(client, 'POST', '/api/v1/categories', {'name': '批量目标'}, 201)
    originals = []
    for index, name in enumerate(['设备整理-同名.md', '设备整理-同名.md', '设备整理-操作.txt', '设备整理-联系.txt']):
        raw = (f'# 设备故障处理 {index}\n\n借用设备出现故障时停止使用，记录现象和发现时间，联系设备管理员安排维修或替代设备，不要自行拆机。\n').encode()
        row = wait_document(client, upload(client, name, raw)['id'], 'ready')
        api(client, 'PATCH', f'/api/v1/documents/{row["id"]}/category', {'categoryId': source['id']})
        originals.append((row, raw))
    identities = [r['id'] for r, _ in originals]
    def move(ids, destination=target['id'], expected=200):
        response = api(client, 'PATCH', '/api/v1/documents/batch/category', {'categoryId': destination, 'documentIds': ids}, expected)
        report['observations'].append({'ids': ids, 'target': destination, 'http': expected, 'response': response})
        return response
    missing = str(uuid.uuid4())
    mixed = move([identities[0], identities[1], identities[0], missing])
    assert mixed['succeededCount'] == 2 and mixed['failedCount'] == 1 and len(mixed['items']) == 3
    assert mixed['items'][-1]['documentId'] == missing and not mixed['items'][-1]['success']
    def counts():
        return {c['id']: c['activeCount'] for c in api(client, 'GET', '/api/v1/categories')['items']}
    assert counts()[source['id']] == 2 and counts()[target['id']] == 2
    report['checks'].append({'check': 'partial_missing_file_dedup_same_names_counts', 'passed': True})
    repeated = move(identities[:2]); assert repeated['succeededCount'] == 2 and all(not x['changed'] for x in repeated['items'])
    failed_retry = move([missing]); assert failed_retry['failedCount'] == 1 and counts()[target['id']] == 2
    report['checks'].append({'check': 'idempotent_repeat_failure_only_retry_no_duplicate_count', 'passed': True})
    move(identities[2:], str(uuid.uuid4()), 404)
    assert counts()[source['id']] == 2 and counts()[target['id']] == 2
    for ids in [[], [identities[2]] * 101, ['invalid-id']]: move(ids, expected=422)
    report['checks'].append({'check': 'invalid_target_empty_oversize_bad_ids_no_changes', 'passed': True})
    for kind, q in [('list', None), ('keyword', '设备管理员'), ('semantic', '借用的器材坏了需要怎样处理？')]:
        for cat, wanted in [(source['id'], set(identities[2:])), (target['id'], set(identities[:2]))]:
            params = {'category_id': cat, 'limit': 25}
            path = '/api/v1/documents' if kind == 'list' else '/api/v1/search/' + kind
            if q: params.update(q=q)
            if kind == 'semantic': params['score_window'] = 1
            response = api(client, 'GET', path + '?' + urllib.parse.urlencode(params))
            assert {r['id'] for r in response['items']} == wanted, (kind, response)
            report['observations'].append({'kind': kind, 'category': cat, 'response': response})
    name_results = api(client, 'GET', '/api/v1/documents?' + urllib.parse.urlencode({'name_query': '同名', 'category_id': target['id'], 'limit': 1}))
    assert name_results['total'] == 2 and len(name_results['items']) == 1
    body_only = api(client, 'GET', '/api/v1/documents?name_query=' + urllib.parse.quote('设备管理员'))
    assert body_only['total'] == 0, 'Picker name search must not match body'
    literal = api(client, 'GET', '/api/v1/documents?name_query=%25')
    assert literal['total'] == 0
    report['checks'].append({'check': 'refresh_metadata_name_only_query_paging_keyword_semantic_category_filters', 'passed': True})
    archived = api(client, 'POST', f'/api/v1/documents/{identities[3]}/archive')
    move([identities[3]], None)
    reread = api(client, 'GET', f'/api/v1/documents/{identities[3]}')
    assert reread['archivedAt'] == archived['archivedAt'] and reread['category'] is None
    report['checks'].append({'check': 'archived_file_move_to_unclassified_retains_archive', 'passed': True})
    api(client, 'POST', f'/api/v1/documents/{identities[3]}/restore')
    move(identities, source['id'])
    for row, raw in originals:
        check = download_equal(client, api(client, 'GET', f'/api/v1/documents/{row["id"]}'), raw)
        report['observations'].append({'id': row['id'], 'download': check})
    report['checks'].append({'check': 'all_original_download_bytes_and_sha_unchanged', 'passed': True})
    # New files for browser multi-page selection; do not pollute the demo service.
    for index in range(21): upload(client, f'分页整理-{index:02d}.txt', f'分页浏览样本{index}'.encode())
    report['browserFixture'] = {'source': source, 'target': target, 'documents': [r for r, _ in originals]}


def main():
    configure_utf8_io(); p = argparse.ArgumentParser(); p.add_argument('--report', type=Path, required=True); args = p.parse_args()
    report = {'type': 'automated Docker real TCP HTTP', 'checks': [], 'observations': [], 'failure': None}
    start = time.perf_counter()
    try: verify(TcpClient('http://127.0.0.1:8000'), report)
    except Exception as error:
        import traceback
        traceback.print_exc(); report['failure'] = repr(error)
    report['seconds'] = round(time.perf_counter()-start, 3)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'checks': len(report['checks']), 'seconds': report['seconds'], 'failure': report['failure']}, ensure_ascii=False))
    if report['failure']: raise SystemExit(1)


if __name__ == '__main__': main()
