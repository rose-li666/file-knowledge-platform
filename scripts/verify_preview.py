"""Read-only real HTTP preview checks against isolated uploaded corpus."""
import hashlib
import json
import os
from pathlib import Path
from verify_m2 import TcpClient
from verify_m5 import api
assert os.environ.get('ACCEPTANCE_TEST_RUN')
client=TcpClient('http://127.0.0.1:8000');rows=api(client,'GET','/api/v1/documents')['items']
result=[]
for row in rows:
    if row['extension'] != 'pdf':continue
    status,raw,headers=client.request('GET',f"/api/v1/documents/{row['id']}/preview")
    assert status==200 and hashlib.sha256(raw).hexdigest()==row['sha256']
    assert headers['content-disposition'].startswith('inline') and headers['content-type']=='application/pdf'
    result.append({'id':row['id'],'name':row['name'],'sha256':row['sha256'],'status':status,'headers':dict(headers)})
assert len(result)==3
text=next(row for row in rows if row['extension']=='txt')
api(client,'GET',f"/api/v1/documents/{text['id']}/preview",expected=409)
path=Path('/tmp/check-reports/preview.json');path.write_text(json.dumps({'checks':result,'textRejected409':True},ensure_ascii=False,indent=2),encoding='utf-8')
print('3 PDF preview bytes equal original SHA; TXT rejected409')
