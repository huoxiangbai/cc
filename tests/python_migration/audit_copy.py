#!/usr/bin/env python3
"""Read only an explicitly acknowledged test-copy root. Never makes network calls."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote


def inside(root, path):
    root=root.resolve(strict=True)
    path=Path(path)
    path=path if path.is_absolute() else root/path
    resolved=path.resolve(strict=True)
    if not resolved.is_relative_to(root) or path.is_symlink():
        raise ValueError('Input escapes test-copy root or is a symlink')
    # Reject symlinks at every path component, including in-root links.
    if any(p.is_symlink() for p in [path,*path.parents] if p.is_relative_to(root)):
        raise ValueError('Symlink input is not allowed')
    return resolved


def ddl_snapshot(text):
    """Preserve column/constraint/options; ignore dump preamble and AUTO_INCREMENT counter."""
    tables={}
    for match in re.finditer(r'CREATE TABLE\s+(?:IF NOT EXISTS\s+)?`?(\w+)`?\s*\((.*?)\)\s*([^;]*);',text,re.I|re.S):
        body=match.group(2)
        # Only indentation/line endings and current sequence value are normalized.
        definitions=[line.strip().rstrip(',') for line in body.splitlines() if line.strip()]
        options=re.sub(r'\bAUTO_INCREMENT=\d+\s*','',match.group(3),flags=re.I)
        tables[match.group(1)]={'definitions':definitions,'options':re.sub(r'\s+',' ',options).strip()}
    if not tables:raise ValueError('No CREATE TABLE found')
    return tables


def sqlite_snapshot(path):
    # Read-only URI, query_only, never create DB or import Tool Runtime (create_all).
    with sqlite3.connect('file:'+quote(str(path))+'?mode=ro&immutable=1',uri=True) as conn:
        conn.execute('PRAGMA query_only=ON')
        tables={}
        for name,sql in conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            tables[name]={'sql':sql,'columns':[list(row) for row in conn.execute('PRAGMA table_info('+json.dumps(name)+')')],
                          'indexes':[list(row) for row in conn.execute('PRAGMA index_list('+json.dumps(name)+')')],
                          'foreignKeys':[list(row) for row in conn.execute('PRAGMA foreign_key_list('+json.dumps(name)+')')],
                          'rows':conn.execute('SELECT COUNT(*) FROM "'+name.replace('"','""')+'"').fetchone()[0]}
        return {'integrity':conn.execute('PRAGMA integrity_check').fetchone()[0],'tables':tables}


def check_files(root, entries):
    errors=[];registered={}
    for i,entry in enumerate(entries):
        try:
            p=inside(root,entry['relativePath'])
            digest=hashlib.md5(p.read_bytes()).hexdigest()
            if p.stat().st_size!=entry['fileSize']:errors.append(f'entry[{i}]: size mismatch')
            if entry.get('fileHash') and digest!=entry['fileHash']:errors.append(f'entry[{i}]: md5 mismatch')
            if not all(entry.get(key) is not None for key in ('artifactId','fileId','requestId','storageKey','previewUrl','downloadUrl')):
                errors.append(f'entry[{i}]: missing association/URL')
            key=entry['storageKey']
            identity=(entry['fileId'],entry['requestId'],p)
            if key in registered and registered[key]!=identity:errors.append(f'entry[{i}]: conflicting storageKey association')
            registered[key]=identity
        except (ValueError,KeyError,OSError) as e:errors.append(f'entry[{i}]: {type(e).__name__}')
    return {'entries':len(entries),'errors':errors,'verified':'metadata/bytes/associations only; URL HTTP access not exercised'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--copy-root',type=Path,required=True)
    p.add_argument('--ack-test-copy',action='store_true',required=True)
    p.add_argument('--mysql-ddl',type=Path)
    p.add_argument('--sqlite',type=Path,action='append',default=[])
    p.add_argument('--sqlite-schema',type=Path,help='Expected snapshot previously exported from a known copy')
    p.add_argument('--files-manifest',type=Path)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();root=args.copy_root.resolve(strict=True)
    result={'evidence':'explicit test-copy offline audit','mysql':'not supplied','sqlite':[],'files':'not supplied'}
    failures=[]
    if args.mysql_ddl:
        expected=ddl_snapshot((Path(__file__).resolve().parents[2]/'Reactor-agent-app/src/main/resources/db/schema.sql').read_text())
        actual=ddl_snapshot(inside(root,args.mysql_ddl).read_text())
        from compare import compare
        failures+=compare(expected,actual)
        result['mysql']={'tables':len(actual),'differences':failures.copy(),'limit':'DDL only, not row/transaction/collation execution parity'}
    for path in args.sqlite:
        snapshot=sqlite_snapshot(inside(root,path));result['sqlite'].append(snapshot)
        if snapshot['integrity']!='ok':failures.append('SQLite integrity failure')
    if args.sqlite_schema:
        from compare import compare
        expected=json.loads(inside(root,args.sqlite_schema).read_text())
        # Row counts are retained: compare against the same consistent snapshot.
        failures+=compare(expected,result['sqlite'])
    if args.files_manifest:
        result['files']=check_files(root,json.loads(inside(root,args.files_manifest).read_text()));failures+=result['files']['errors']
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    if failures:raise SystemExit(f'{len(failures)} validation failures; inspect output (contains metadata, keep local)')
    print('PASS: supplied test-copy inputs only; omitted inputs remain unverified')

if __name__=='__main__':main()
