"""Read real browser results; test transaction rollback/retry in owned test DB."""
import json
import os
import sqlite3
import time
import urllib.parse
from pathlib import Path
from utf8_logs import configure_utf8_io
from verify_m2 import TcpClient
from verify_m5 import api


def main():
    configure_utf8_io(); assert os.environ.get('ACCEPTANCE_TEST_RUN')
    base = Path('/tmp/check-reports'); client = TcpClient('http://127.0.0.1:8000')
    fixture = json.loads((base/'batch.json').read_text(encoding='utf-8'))['browserFixture']
    ids = [r['id'] for r in fixture['documents']]
    categories = api(client, 'GET', '/api/v1/categories')['items']
    source, target = fixture['source']['id'], fixture['target']['id']
    browser = next(c['id'] for c in categories if c['name'] == '浏览器批量目标')
    report = {'type': 'Docker actual HTTP after IAB; controlled SQL fault for rollback', 'checks': [], 'observations': []}
    start = time.perf_counter()
    expected = {source: set(), target: set(ids[:2]), browser: set(ids[2:])}
    for kind, query in [('list', None), ('keyword', '设备管理员'), ('semantic', '借用的器材坏了需要怎样处理？')]:
        for category, wanted in expected.items():
            params = {'category_id': category}
            path = '/api/v1/documents' if kind == 'list' else '/api/v1/search/' + kind
            if query: params['q'] = query
            if kind == 'semantic': params['score_window'] = 1
            response = api(client, 'GET', path + '?' + urllib.parse.urlencode(params))
            assert {r['id'] for r in response['items']} == wanted
            report['observations'].append({'kind': kind, 'category': category, 'response': response})
    assert {c['id']: c['activeCount'] for c in categories if c['id'] in expected} == {source: 0, target: 2, browser: 2}
    report['checks'].append({'check': 'browser_moves_refresh_counts_keyword_semantic_current_category', 'passed': True})
    # Database write failure must roll back the whole valid batch, then be safe to retry.
    connection = sqlite3.connect('/data/db/platform.sqlite3', timeout=5)
    connection.execute("CREATE TRIGGER batch_test_write_failure BEFORE UPDATE OF category_id ON documents WHEN NEW.id='" + ids[1] + "' BEGIN SELECT RAISE(ABORT, 'isolated batch write fault'); END")
    connection.commit()
    try:
        response = api(client, 'PATCH', '/api/v1/documents/batch/category', {'categoryId': source, 'documentIds': ids[:2]}, 503)
        assert response['error']['retryable']
        reread = api(client, 'GET', '/api/v1/documents?category_id=' + target)
        assert {r['id'] for r in reread['items']} == set(ids[:2])
        report['observations'].append({'http': 503, 'response': response})
    finally:
        connection.execute('DROP TRIGGER batch_test_write_failure'); connection.commit(); connection.close()
    retry = api(client, 'PATCH', '/api/v1/documents/batch/category', {'categoryId': source, 'documentIds': ids[:2]})
    assert retry['succeededCount'] == 2
    api(client, 'PATCH', '/api/v1/documents/batch/category', {'categoryId': target, 'documentIds': ids[:2]})
    report['checks'].append({'check': 'real_database_failure_atomic_rollback_and_retry', 'passed': True})
    import hashlib
    for row in fixture['documents']:
        saved = api(client, 'GET', '/api/v1/documents/' + row['id'])
        status, raw, _ = client.request('GET', saved['downloadUrl'])
        assert status == 200 and hashlib.sha256(raw).hexdigest() == row['sha256']
        assert saved['vectorStatus'] == 'ready' and saved['chunkCount'] == row['chunkCount']
        report['observations'].append({'id': row['id'], 'originalSha256': row['sha256'], 'downloadSha256': hashlib.sha256(raw).hexdigest(), 'vectorStatus': saved['vectorStatus'], 'chunkCount': saved['chunkCount']})
    report['checks'].append({'check': 'fault_restored_metadata_vectors_original_download_sha', 'passed': True})
    report['seconds'] = round(time.perf_counter()-start, 3)
    (base/'post-browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'checks': len(report['checks']), 'seconds': report['seconds'], 'passed': True}))


if __name__ == '__main__': main()
