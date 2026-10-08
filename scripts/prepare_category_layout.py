"""Long category list fixture; run only inside an owned acceptance container."""
import json
import os
from pathlib import Path
from utf8_logs import configure_utf8_io
from verify_m2 import TcpClient
from verify_m5 import api


def main():
    configure_utf8_io()
    assert os.environ.get('ACCEPTANCE_TEST_RUN'), 'Requires isolated acceptance container marker'
    client = TcpClient('http://127.0.0.1:8000')
    rows = api(client, 'GET', '/api/v1/documents')['items']
    assert len(rows) == 1 and rows[0]['name'] == '分类归档链路.txt'
    assert len(api(client, 'GET', '/api/v1/categories')['items']) == 2, 'Fresh acceptance run required'
    categories = [api(client, 'POST', '/api/v1/categories',
        {'name': f'布局验收-{number:02d}-长名称完整展示与键盘滚动检查的分类资料'}, 201)
        for number in range(1, 41)]
    target = categories[-1]
    api(client, 'PATCH', f'/api/v1/documents/{rows[0]["id"]}/category', {'categoryId': target['id']})
    result = {'category': target, 'documentId': rows[0]['id'], 'categoryCount': 42,
              'type': 'isolated HTTP fixture, not browser interaction evidence'}
    path = Path('/tmp/check-reports/layout-fixture.json')
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
