"""Build/start once and record main-service uploads plus isolated container faults."""
import argparse
import json
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from utf8_logs import configure_utf8_io

ROOT = Path(__file__).resolve().parents[1]


def main():
    configure_utf8_io()
    parser = argparse.ArgumentParser()
    parser.add_argument('--zip', type=Path, required=True)
    parser.add_argument('--skip-build', action='store_true')
    args = parser.parse_args()
    fixture = args.zip.resolve(strict=True)
    reports = ROOT.parent/'m5-docker'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:6])
    reports.mkdir(parents=True)
    name = 'm5-verification-'+uuid.uuid4().hex[:12]
    summary = {'steps': [], 'failure': None, 'browser': 'not verified by this runner'}
    started = time.perf_counter()
    def run(label, command, required=True):
        clock = time.perf_counter()
        print('Executing: '+subprocess.list2cmdline(command), flush=True)
        code = None
        with (reports/(label+'.log')).open('w',encoding='utf-8') as log:
            log.write('Command: '+subprocess.list2cmdline(command)+'\n')
            try:
                process=subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                         encoding='utf-8',errors='backslashreplace')
                for line in process.stdout:
                    print(line,end='',flush=True); log.write(line); log.flush()
                code=process.wait()
            except OSError as error:
                log.write(str(error)+'\n')
            seconds=round(time.perf_counter()-clock,3)
            log.write(f'\nExit code: {code}; seconds: {seconds}\n')
        summary['steps'].append({'step':label,'command':command,'exit_code':code,'seconds':seconds})
        if required and code != 0: raise RuntimeError(f'{label} failed; later validation steps stopped')
    try:
        if not args.skip_build:
            run('01-build',['docker','compose','--progress','plain','build'])
        run('02-start',['docker','compose','up','-d','--no-build','--wait','--wait-timeout','180'])
        # No report bind-directory permission assumptions; copy reports out afterward.
        run('03-verify',['docker','compose','run','--no-deps','--name',name,
            '-v',f'{fixture}:/fixtures/test-documents.zip:ro','app','python','scripts/verify_m5.py',
            '--base-url','http://app:8000','--data-dir','/data','--fault-dir','/tmp/m5-faults',
            '--zip','/fixtures/test-documents.zip','--report','/tmp/m5-reports/results.json'])
    except Exception as error:
        summary['failure']=str(error)
    finally:
        run('04-copy-evidence',['docker','cp',name+':/tmp/m5-reports/.',str(reports)],required=False)
        run('05-app-logs',['docker','compose','logs','--tail=150','app'],required=False)
        run('06-clean-test-container',['docker','rm','-f',name],required=False)
        summary['totalSeconds']=round(time.perf_counter()-started,3)
        (reports/'execution-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Evidence: '+str(reports),flush=True)
    if summary['failure']: raise SystemExit(summary['failure'])


if __name__ == '__main__': main()
