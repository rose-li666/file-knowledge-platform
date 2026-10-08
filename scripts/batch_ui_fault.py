"""Hide/restore one fixture's DB rows to exercise real partial-failure UI safely.

Original bytes remain on disk. This is explicit fault injection, not a user action.
Never import/use this helper in the application.
"""
import argparse
import json
import os
import sqlite3
from pathlib import Path
from utf8_logs import configure_utf8_io


def main():
    configure_utf8_io(); p = argparse.ArgumentParser()
    p.add_argument('action', choices=('hide', 'restore')); p.add_argument('--document-id', required=True); args = p.parse_args()
    assert os.environ.get('ACCEPTANCE_TEST_RUN'), 'Requires owned isolated container marker'
    fixture = json.loads(Path('/tmp/check-reports/batch.json').read_text(encoding='utf-8'))
    assert args.document_id in [row['id'] for row in fixture['browserFixture']['documents']]
    path = Path('/tmp/check-reports/hidden-file.json')
    tables = [('documents', 'id'), ('document_texts', 'document_id'), ('index_jobs', 'document_id'), ('chunks', 'document_id')]
    with sqlite3.connect('/data/db/platform.sqlite3', timeout=5) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON'); connection.execute('BEGIN IMMEDIATE')
        if args.action == 'hide':
            assert not path.exists(), 'One hide at a time'
            rows = {table: [dict(row) for row in connection.execute(f'SELECT * FROM {table} WHERE {key}=?', (args.document_id,))] for table, key in tables}
            assert len(rows['documents']) == 1 and rows['documents'][0]['vector_status'] == 'ready'
            encode = lambda value: {'bytesHex': value.hex()} if isinstance(value, bytes) else value
            data = {'id': args.document_id, 'rows': {table: [{k: encode(v) for k, v in row.items()} for row in values] for table, values in rows.items()}}
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            connection.execute('DELETE FROM documents WHERE id=?', (args.document_id,))
        else:
            data = json.loads(path.read_text(encoding='utf-8')); assert data['id'] == args.document_id
            assert connection.execute('SELECT id FROM documents WHERE id=?', (args.document_id,)).fetchone() is None
            for table, _ in tables:
                for row in data['rows'][table]:
                    values = [bytes.fromhex(v['bytesHex']) if isinstance(v, dict) else v for v in row.values()]
                    connection.execute(f'INSERT INTO {table} ({",".join(row)}) VALUES ({",".join("?" for _ in row)})', values)
        connection.commit()
    print(json.dumps({'type': 'controlled isolated DB fault injection; original disk bytes unchanged', 'action': args.action, 'documentId': args.document_id, 'passed': True}))


if __name__ == '__main__': main()
