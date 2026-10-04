"""Privileged local Skill package maintenance; HTTP admin transport remains P5.

The explicit --authorized-root prevents accidental mutation of a discovered
repository/runtime directory. It is an operator boundary, never an agent tool.
"""
import argparse
import asyncio
import json
from pathlib import Path
import httpx
from reactor_backend.skills.registry import Registry


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--authorized-root',action='store_true',required=True)
    sub=parser.add_subparsers(dest='operation',required=True)
    sub.add_parser('list');sub.add_parser('reload')
    for op in ('preview','import-package'):
        p=sub.add_parser(op);p.add_argument('--file',type=Path,required=True)
        if op=='import-package':p.add_argument('--replace',action='store_true')
    p=sub.add_parser('create');p.add_argument('--file',type=Path,required=True);p.add_argument('--name');p.add_argument('--replace',action='store_true')
    p=sub.add_parser('import-url');p.add_argument('--url',required=True);p.add_argument('--replace',action='store_true')
    p=sub.add_parser('delete');p.add_argument('--name',required=True)
    args=parser.parse_args()
    if not args.root.is_absolute():raise ValueError('Use an explicit absolute authorized Skill root')
    registry=Registry(args.root)
    if args.operation in ('list','reload'):result=registry.list()
    elif args.operation=='preview':result=registry.preview(args.file.read_bytes())
    elif args.operation=='import-package':result=registry.install(args.file.read_bytes(),args.replace)
    elif args.operation=='create':result=registry.create(dict(content=args.file.read_text(),name=args.name,replace=args.replace))
    elif args.operation=='delete':result=registry.delete(args.name)
    else:
        async def download():
            async with httpx.AsyncClient(timeout=60,trust_env=False) as client:return await registry.import_url(client,args.url,args.replace)
        result=asyncio.run(download())
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
