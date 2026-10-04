"""Explicit maintenance commands. Never invoked by backend startup."""
import argparse
import asyncio
import os
from pathlib import Path
import sqlite3
from sqlglot import parse, exp


def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='operation',required=True)
    acl=sub.add_parser('acl-migrate');acl.add_argument('--authorized-copy',action='store_true',required=True)
    for name in ('admin-migrate','featured-migrate'):
        sub.add_parser(name).add_argument('--authorized-copy',action='store_true',required=True)
    admin=sub.add_parser('admin-init');admin.add_argument('--authorized-copy',action='store_true',required=True);admin.add_argument('--username',required=True);admin.add_argument('--user-id',required=True)
    init=sub.add_parser('sqlite-init');init.add_argument('--path',type=Path,required=True);init.add_argument('--schema',type=Path,required=True)
    init.add_argument('--authorized-copy',action='store_true',required=True)
    args=parser.parse_args()
    if args.operation=='sqlite-init':
        path=args.path
        if not path.is_absolute():raise ValueError('Use an explicit absolute new database path')
        statements=parse(args.schema.read_text(),read='sqlite')
        if any(not isinstance(s,(exp.Create,exp.Insert)) for s in statements):raise ValueError('Initialization accepts CREATE/INSERT only; no DROP or legacy scripts')
        # Exclusive creation prevents typo-driven replacement or reuse of an existing DB.
        with path.open('xb'):pass
        try:
            with sqlite3.connect(path) as c:
                for statement in statements:c.execute(statement.sql(dialect='sqlite'))
        except BaseException:
            # Preserve partially initialized new file for inspection; never delete/retry silently.
            raise
        print('New SQLite business database initialized')
    else:
        from reactor_backend.adapters.mysql import MySQLLedger
        from sqlalchemy import text
        url=os.environ.get('REACTOR_MYSQL_URL')
        if not url:raise ValueError('Explicit authorized REACTOR_MYSQL_URL required')
        async def migrate():
            ledger=MySQLLedger(url)
            try:
                from importlib.resources import files
                if args.operation=='admin-init':
                    import getpass
                    password=os.environ.get('REACTOR_ADMIN_INIT_PASSWORD') or getpass.getpass('New isolated/admin password: ')
                    if not password:raise ValueError('Password required')
                    def initialize(c):
                        from reactor_backend.adapters.mysql import rows
                        if rows(c,'SELECT id FROM admin_user LIMIT 1 FOR UPDATE'):raise ValueError('Admin initialization requires an empty admin table')
                        c.execute(text('INSERT INTO admin_user(user_id,username,password,status) VALUES(:id,:name,:password,1)'),dict(id=args.user_id,name=args.username,password=password))
                    await ledger.transact(initialize)
                    return
                name={'acl-migrate':'001_private_resource_acl.sql','admin-migrate':'002_admin_session.sql','featured-migrate':'003_featured_resource.sql'}[args.operation]
                script=files('reactor_backend').joinpath('resources/migrations/'+name)
                sql='CREATE TABLE'+script.read_text().split('CREATE TABLE',1)[1]
                await ledger.transact(lambda c:c.execute(text(sql)))
            finally:await ledger.close()
        asyncio.run(migrate())
        print('Explicit '+args.operation+' completed')


if __name__=='__main__':main()
