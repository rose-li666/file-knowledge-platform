"""Independent Compose project and new named volume; no changes to user's app volume."""
import argparse
import json
import os
import socket
import subprocess
import time
import uuid
from datetime import datetime,timezone
from pathlib import Path

from utf8_logs import configure_utf8_io

ROOT=Path(__file__).resolve().parents[1]


def main():
    configure_utf8_io();parser=argparse.ArgumentParser()
    parser.add_argument('--zip',type=Path,required=True);args=parser.parse_args()
    fixture=args.zip.resolve(strict=True)
    project='m6-'+uuid.uuid4().hex[:12]
    reports=ROOT.parent/'m6-docker'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+project)
    reports.mkdir(parents=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    environment=dict(os.environ,APP_PORT=str(port))
    compose=['docker','compose','-p',project,'-f',str(ROOT/'compose.yaml')]
    summary={'project':project,'port':port,'steps':[],'failure':None,'volumeRetained':project+'_platform_data',
             'scope':'new independent volume; user knowledge-platform volume untouched'}
    started=time.perf_counter()
    def run(label,command,required=True):
        clock=time.perf_counter();print('Executing: '+subprocess.list2cmdline(command),flush=True)
        code=None
        with (reports/(label+'.log')).open('w',encoding='utf-8') as log:
            log.write('Command: '+subprocess.list2cmdline(command)+'\n')
            try:
                process=subprocess.Popen(command,cwd=ROOT,env=environment,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                         encoding='utf-8',errors='backslashreplace')
                for line in process.stdout:
                    print(line,end='',flush=True);log.write(line);log.flush()
                code=process.wait()
            except OSError as error: log.write(str(error)+'\n')
            seconds=round(time.perf_counter()-clock,3);log.write(f'\nExit code: {code}; seconds: {seconds}\n')
        summary['steps'].append({'step':label,'command':command,'exit_code':code,'seconds':seconds})
        if required and code != 0: raise RuntimeError(label+' failed; dependent checks stopped')
    def verify(label,phase,before=None,restore=False):
        name=project+'-verify-'+uuid.uuid4().hex[:6]
        command=compose+['run','--no-deps','--name',name,'-v',f'{fixture}:/fixtures/documents.zip:ro']
        if before: command += ['-v',f'{before}:/fixtures/before.json:ro']
        command += ['app','python','scripts/verify_m6.py','--phase',phase,'--zip','/fixtures/documents.zip',
                    '--report','/tmp/m6-reports/'+label+'.json']
        if before: command += ['--before','/fixtures/before.json']
        if restore: command += ['--restore']
        try: run(label,command)
        finally:
            run(label+'-copy',['docker','cp',name+':/tmp/m6-reports/.',str(reports)],required=False)
            run(label+'-clean',['docker','rm','-f',name],required=False)
    try:
        run('01-fresh-build-start',compose+['up','--build','-d','--wait','--wait-timeout','180'])
        run('02-volume-inspect',['docker','volume','inspect',project+'_platform_data'])
        run('03-container-inspect',['docker','inspect',project+'-app-1'])
        name=project+'-review'
        try:
            run('03-review-after',compose+['run','--no-deps','--name',name,'app','python',
                'scripts/verify_m6_review.py','--data-dir','/tmp/m6-review','--model-dir','/opt/models/bge',
                '--report','/tmp/m6-review-reports/03-review-after.json'])
        finally:
            run('03-review-copy',['docker','cp',name+':/tmp/m6-review-reports/.',str(reports)],required=False)
            run('03-review-clean',['docker','rm','-f',name],required=False)
        verify('04-prepare','prepare')
        before=reports/'04-prepare.json'
        run('05-restart',compose+['restart','app'])
        run('06-restart-ready',compose+['up','-d','--no-build','--wait','--wait-timeout','180'])
        verify('07-after-restart','after',before)
        run('08-force-recreate',compose+['up','-d','--no-build','--force-recreate','--wait','--wait-timeout','180'])
        verify('09-after-recreate','after',before,restore=True)
    except Exception as error: summary['failure']=str(error)
    finally:
        run('10-app-logs',compose+['logs','--tail=200','app'],required=False)
        # Retain test volume/evidence; only stop this newly-created project.
        run('11-stop-test-project',compose+['down'],required=False)
        summary['seconds']=round(time.perf_counter()-started,3)
        (reports/'execution-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Evidence: '+str(reports),flush=True)
    if summary['failure']: raise SystemExit(summary['failure'])


if __name__ == '__main__':main()
