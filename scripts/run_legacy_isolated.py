"""Historical entry points now dispatch the final isolated regression."""
import argparse
import subprocess
import sys
from pathlib import Path
from utf8_logs import configure_utf8_io

def main():
    configure_utf8_io();parser=argparse.ArgumentParser()
    parser.add_argument('--zip',type=Path,required=True)
    parser.add_argument('--skip-build',action='store_true')
    parser.add_argument('--report-dir',type=Path)
    parser.add_argument('--port',type=int)
    args=parser.parse_args()
    print('Historical entry point: running final regression in a new Compose project/volume. Legacy skip-build/port/report options are ignored; no demo writes.')
    command=[sys.executable,str(Path(__file__).with_name('run_m6_docker.py')),'--zip',str(args.zip)]
    raise SystemExit(subprocess.call(command))
