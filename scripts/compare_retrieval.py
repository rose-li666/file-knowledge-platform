"""Isolated new-upload comparison. Judging labels never enter application ranking."""
import argparse
import json
import os
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.embedding import LocalEmbedder, SPEC
from app.text_normalization import search_key
from utf8_logs import configure_utf8_io
from verify_m2 import TcpClient
from verify_m5 import api, download_equal, upload, wait_document
from verify_retrieval_quality import query


def grade(source, case):
    if source is None:
        return 0
    if any(anchor in source['text'] for anchor in case['strongAnchors']):
        return 2
    if any(anchor in source['text'] for anchor in case['weakAnchors']):
        return 1
    return 0


def rank(chunks, vector, body_vectors, category, variant):
    minimum = .50 if variant == 'floor_050' else .45
    window = {'window_008': .08, 'window_005': .05}.get(variant, .12)
    best = {}
    for index, chunk in enumerate(chunks):
        if category and chunk['category_id'] != category:
            continue
        score = float(np.frombuffer(chunk['embedding'], dtype='<f4') @ vector)
        if score < minimum:
            continue
        doc = best.setdefault(chunk['document_id'], {'id': chunk['document_id'], 'name': chunk['name'], 'score': score, 'sources': []})
        doc['score'] = max(score, doc['score'])
        doc['sources'].append({'ordinal': chunk['ordinal'], 'heading': chunk['heading'], 'text': chunk['text'],
                               'score': round(score, 6), 'bodyScore': round(float(body_vectors[index] @ vector), 6)})
    ordered = sorted(best.values(), key=lambda item: (-item['score'], item['id']))
    if ordered:
        floor = max(minimum, ordered[0]['score'] - window)
        ordered = [row for row in ordered if row['score'] >= floor]
    for row in ordered:
        row['score'] = round(row['score'], 6)
        sources = [s for s in row['sources'] if s['score'] >= row['score'] - .08]
        if variant == 'short_source_penalty':
            key = lambda s: (-(s['score'] - .04 * (1 - min(len(s['text']) / 80, 1))), s['ordinal'])
        elif variant == 'body_source_rerank':
            key = lambda s: (-s['bodyScore'], -s['score'], s['ordinal'])
        else:
            key = lambda s: (-s['score'], s['ordinal'])
        row['sources'] = sorted(sources, key=key)[:2]
    return ordered[:5]


def measure(items, case):
    names = [row['name'] for row in items]
    target = next((row for row in items if row['name'] == case['target']), None)
    return {'targetRank': names.index(case['target']) + 1 if target else None,
            'returned': len(items), 'irrelevantByDeclaredLabels': [name for name in names if name not in case['relevantNames']],
            'firstSourceGrade': grade(target['sources'][0] if target and target['sources'] else None, case),
            'bestTwoSourceGrade': max([grade(s, case) for s in target['sources']] or [0]) if target else 0}


def compare(args, report):
    assert os.environ.get('ACCEPTANCE_TEST_RUN'), 'Requires independently created container marker'
    client = TcpClient('http://127.0.0.1:8000')
    assert api(client, 'GET', '/api/v1/documents')['total'] == 0
    assert not api(client, 'GET', '/api/v1/categories')['items']
    manifest = json.loads(args.cases.read_text('utf-8'))
    report['manifest'] = manifest
    core = api(client, 'POST', '/api/v1/categories', {'name': '语义对照-统一资料'}, 201)
    extra = api(client, 'POST', '/api/v1/categories', {'name': '语义对照-新增资料'}, 201)
    originals = {}
    with zipfile.ZipFile(args.zip) as archive:
        for entry in archive.infolist():
            if entry.is_dir() or Path(entry.filename).suffix.lower() not in {'.pdf', '.txt', '.md'}:
                continue
            name, raw = Path(entry.filename).name, archive.read(entry)
            saved = upload(client, name, raw)
            api(client, 'PATCH', f'/api/v1/documents/{saved["id"]}/category', {'categoryId': core['id']})
            if not name.endswith('.pdf'):
                saved = wait_document(client, saved['id'], 'ready')
            originals[name] = saved
            report['downloads'].append({'name': name, **download_equal(client, saved, raw)})
    assert len(originals) == 10
    for fixture in manifest['fixtures']:
        raw = (args.cases.parent / 'fixtures' / fixture['path']).read_bytes()
        saved = upload(client, fixture['uploadName'], raw)
        api(client, 'PATCH', f'/api/v1/documents/{saved["id"]}/category', {'categoryId': extra['id']})
        saved = wait_document(client, saved['id'], 'ready')
        report['downloads'].append({'name': fixture['uploadName'], **download_equal(client, saved, raw)})
    # Read only the new business database. Variants use its same real persisted chunks.
    with sqlite3.connect('file:/data/db/platform.sqlite3?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        chunks = [dict(row) for row in db.execute('''SELECT c.*, d.name, d.category_id, d.chunk_count
            FROM chunks c JOIN documents d ON d.id=c.document_id JOIN index_jobs j ON j.document_id=d.id
            WHERE d.archived_at IS NULL AND d.text_status='ready' AND d.vector_status='ready'
            AND j.state='ready' AND c.generation=j.generation AND c.model_revision=?
            ORDER BY c.document_id,c.ordinal''', (SPEC['revision'],))]
    chunks = [c for c in chunks if not (c['chunk_count'] > 1 and search_key(c['text']).strip() == search_key(c['heading']).strip())]
    model = LocalEmbedder(Path('/opt/models/bge'))
    clock = time.perf_counter()
    body_vectors = model.encode([c['text'] for c in chunks])
    report['bodyVectorPreparationSeconds'] = round(time.perf_counter() - clock, 3)
    report['chunkCount'] = len(chunks)
    report['categoryIds'] = {'core': core['id'], 'extra': extra['id']}
    variants = ['baseline', 'floor_050', 'window_008', 'window_005', 'short_source_penalty', 'body_source_rerank']
    for case in manifest['cases']:
        category = core['id'] if case['scope'] == 'core' else None
        clock = time.perf_counter()
        vector = model.encode([case['question']], query=True)[0]
        http = query(client, case['question'], **({'category_id': category} if category else {}))
        entry = {'case': case, 'httpResponse': http, 'httpVariant': args.http_variant, 'variants': {}}
        for variant in variants:
            items = rank(chunks, vector, body_vectors, category, variant)
            entry['variants'][variant] = {'items': items, 'metrics': measure(items, case)}
        expected = entry['variants'][args.http_variant]['items']
        assert [r['id'] for r in expected] == [r['id'] for r in http['items']], ('Offline/HTTP mismatch', case['id'])
        for calculated, returned in zip(expected, http['items']):
            assert abs(calculated['score'] - returned['score']) <= .00001
            assert [s['ordinal'] for s in calculated['sources']] == [s['ordinal'] for s in returned['sources']]
        entry['seconds'] = round(time.perf_counter() - clock, 3)
        report['results'].append(entry)
        print(case['id'], {v: entry['variants'][v]['metrics']['targetRank'] for v in variants}, flush=True)
    for variant in variants:
        groups = {}
        for split in ['development', 'holdout', 'all']:
            selected = [e for e in report['results'] if split == 'all' or e['case']['split'] == split]
            positive = [e for e in selected if e['case']['target']]
            negative = [e for e in selected if e['case']['target'] is None]
            changed = [(e['case']['id'], e['variants']['baseline']['metrics'], e['variants'][variant]['metrics']) for e in selected]
            groups[split] = {'positives': len(positive),
                'targetsFound': sum(e['variants'][variant]['metrics']['targetRank'] is not None for e in positive),
                'targetLostFromBaseline': [identity for identity, before, after in changed if before['targetRank'] and not after['targetRank']],
                'originalTop3Misses': [e['case']['id'] for e in positive if e['case']['group'] == 'original' and not (e['variants'][variant]['metrics']['targetRank'] or 99) <= 3],
                'irrelevantCount': sum(len(e['variants'][variant]['metrics']['irrelevantByDeclaredLabels']) for e in selected),
                'negativeNonempty': [e['case']['id'] for e in negative if e['variants'][variant]['metrics']['returned']],
                'newNegativeNonempty': [e['case']['id'] for e in negative if not e['variants']['baseline']['metrics']['returned'] and e['variants'][variant]['metrics']['returned']],
                'firstSourceGradeSum': sum(e['variants'][variant]['metrics']['firstSourceGrade'] for e in positive),
                'sourceGradeRegressions': [identity for identity, before, after in changed if after['firstSourceGrade'] < before['firstSourceGrade']]}
        report['summary'][variant] = groups


def main():
    configure_utf8_io()
    parser = argparse.ArgumentParser()
    parser.add_argument('--zip', type=Path, required=True)
    parser.add_argument('--cases', type=Path, default=Path(__file__).with_name('retrieval_comparison_cases.json'))
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--http-variant', choices=['baseline', 'window_008'], default='window_008',
                        help='Expected production default; no override is sent to HTTP queries')
    args = parser.parse_args()
    report = {'transport': 'isolated Docker HTTP new uploads; variant ranking diagnostic over persisted vectors',
              'results': [], 'downloads': [], 'summary': {}, 'failure': None}
    start = time.perf_counter()
    try:
        compare(args, report)
    except Exception as error:
        import traceback
        traceback.print_exc()
        report['failure'] = repr(error)
    report['seconds'] = round(time.perf_counter() - start, 3)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'seconds': report['seconds'], 'failure': report['failure'], 'summary': report['summary']}, ensure_ascii=False))
    if report['failure']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
