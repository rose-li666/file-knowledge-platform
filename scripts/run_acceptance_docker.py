"""Create own container/volume; never write acceptance fixtures into the demo app."""
import argparse
import json
import subprocess
import time
import uuid
from datetime import datetime,timezone
from pathlib import Path
from utf8_logs import configure_utf8_io

ROOT=Path(__file__).resolve().parents[1]

def main():
    configure_utf8_io();p=argparse.ArgumentParser()
    p.add_argument('--image',default='knowledge-platform-app:latest')
    p.add_argument('--port',type=int,default=18080)
    p.add_argument('--keep-running',action='store_true')
    p.add_argument('--frontend-dir',type=Path)
    p.add_argument('--app-dir',type=Path)
    p.add_argument('--zip',type=Path)
    mode=p.add_mutually_exclusive_group()
    mode.add_argument('--quality',action='store_true')
    mode.add_argument('--comparison',action='store_true')
    p.add_argument('--http-variant',choices=['baseline','window_008'],default='window_008')
    args=p.parse_args()
    identity='platform-check-'+uuid.uuid4().hex[:10]
    reports=ROOT.parent/'acceptance'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+identity)
    reports.mkdir(parents=True)
    summary={'container':identity,'volume':identity+'-data','port':args.port,'image':args.image,'steps':[],'failure':None}
    def run(label,command,required=True):
        started=time.perf_counter();print(subprocess.list2cmdline(command),flush=True)
        completed=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        output=completed.stdout.decode('utf-8',errors='backslashreplace')
        (reports/(label+'.log')).write_text('Command: '+subprocess.list2cmdline(command)+'\n'+output,encoding='utf-8')
        summary['steps'].append({'step':label,'command':command,'exit_code':completed.returncode,
                                 'seconds':round(time.perf_counter()-started,3)})
        print(output,flush=True)
        if required and completed.returncode:raise RuntimeError(label+' failed')
        return output
    started=time.perf_counter()
    try:
        mounts=[]
        if args.frontend_dir:
            front=args.frontend_dir.resolve(strict=True)
            assert (front/'index.html').is_file()
            mounts=['--mount',f'type=bind,source={front},target=/app/frontend/dist,readonly']
        if args.app_dir:
            app_dir=args.app_dir.resolve(strict=True)
            assert (app_dir/'main.py').is_file()
            mounts+=['--mount',f'type=bind,source={app_dir},target=/app/app,readonly']
        if args.quality or args.comparison:
            assert args.zip,'--quality/--comparison requires --zip'
            fixture=args.zip.resolve(strict=True)
            mounts+=['--mount',f'type=bind,source={fixture},target=/fixtures/documents.zip,readonly']
        run('start',['docker','run','-d','--name',identity,'-e','ACCEPTANCE_TEST_RUN='+identity,
            '-p',f'127.0.0.1:{args.port}:8000','--mount',f'type=volume,source={identity}-data,target=/data',
            '--mount',f'type=bind,source={ROOT / "scripts"},target=/app/scripts,readonly',*mounts,args.image])
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            health=subprocess.run(['docker','inspect','--format','{{.State.Health.Status}}',identity],capture_output=True)
            if health.returncode == 0 and health.stdout.strip() == b'healthy':break
            time.sleep(1)
        else:raise RuntimeError('Isolated service health timeout')
        if not (args.quality or args.comparison):
            run('verify',['docker','exec',identity,'python','scripts/verify_acceptance.py','--report','/tmp/check-reports/results.json'])
        if args.quality:
            run('quality',['docker','exec',identity,'python','scripts/verify_retrieval_quality.py',
                '--zip','/fixtures/documents.zip','--report','/tmp/check-reports/quality.json'])
        if args.comparison:
            run('comparison',['docker','exec',identity,'python','scripts/compare_retrieval.py',
                '--zip','/fixtures/documents.zip','--http-variant',args.http_variant,
                '--report','/tmp/check-reports/retrieval.json'])
    except Exception as error:summary['failure']=repr(error)
    finally:
        run('copy',['docker','cp',identity+':/tmp/check-reports/.',str(reports)],False)
        run('logs',['docker','logs',identity],False)
        if not args.keep_running or summary['failure']:
            run('stop',['docker','rm','-f',identity],False)
        summary['seconds']=round(time.perf_counter()-started,3)
        (reports/'execution-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Evidence: '+str(reports))
    if summary['failure']:raise SystemExit(1)

if __name__ == '__main__':main()
