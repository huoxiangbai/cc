#!/usr/bin/env python3
"""Run unchanged workbench sources in the integration harness' NEW root, without dotenv."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import signal
import subprocess

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('isolation_root',type=Path)
    args=parser.parse_args()
    root=args.isolation_root.resolve()
    if not root.name.startswith(('reactor-p1-','reactor-p2-','reactor-p3-','reactor-p4-','reactor-p5-')) or not (root/'ISOLATED_P1').is_file():
        raise ValueError('Use the fresh root printed by integration.py --serve')
    connection=json.loads((root/'connection.json').read_text())
    if Path(connection['isolation_root']).resolve()!=root:raise ValueError('Isolation root mismatch')
    dependencies=ROOT/'ui/node_modules'
    if not dependencies.is_dir():raise RuntimeError('Original UI dependencies must already be installed')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',3000))  # fail explicitly if another UI owns the port
    destination=root/'ui'
    shutil.copytree(ROOT/'ui',destination,ignore=shutil.ignore_patterns('.env*','node_modules','dist','.git'))
    (destination/'node_modules').symlink_to(dependencies,target_is_directory=True)
    (destination/'vite-isolation.config.ts').write_text("import original from './vite.config';\nexport default async (env: any) => {const config=typeof original === 'function' ? await original(env) : await original;return {...config, cacheDir: '.vite-cache',server:{...config.server,fs:{...config.server?.fs,allow:[process.cwd(),"+json.dumps(str(dependencies))+ "]}}};};\n")
    environment={k:v for k,v in os.environ.items() if k in ('PATH','LANG','LC_ALL','TMPDIR','SYSTEMROOT')}
    environment.update(SERVICE_BASE_URL=connection['backend_url'],REACTOR_TOOL_BASE_URL=connection.get('public_tool_url',connection['tool_url']))
    print('Original workbench copy: http://127.0.0.1:3000 ; no .env copied',flush=True)
    process=subprocess.Popen(['npm','run','dev','--','--host','127.0.0.1','--port','3000','--strictPort','--config','vite-isolation.config.ts'],cwd=destination,env=environment,start_new_session=True)
    try:
        if process.wait():raise RuntimeError('Isolated Vite failed')
    finally:
        try:os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        process.wait()


if __name__=='__main__':main()
