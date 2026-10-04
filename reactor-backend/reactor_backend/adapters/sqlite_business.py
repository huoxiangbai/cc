"""Explicit, read-only SQLite business source, separate from Tool metadata.

DECIMAL_TEXT columns keep decimal input lossless; SQL arithmetic/aggregates on
those columns use Decimal functions. A result that cannot survive the original
numeric JSON projection is rejected rather than rounded silently.
"""
import asyncio
from decimal import Decimal, Inexact, Rounded, localcontext
from pathlib import Path
import sqlite3
import threading
import time
import sqlglot
from sqlglot import exp
from reactor_backend.data_query.sql import select_sql,render


def number(raw):
    if raw is None:return None
    value=Decimal(str(raw))
    if not value.is_finite():raise ValueError('Non-finite decimal')
    return value


def project(value):
    if value is None:return None
    d=number(value)
    if d==d.to_integral_value():return int(d)
    f=float(d)
    if Decimal(str(f))!=d:raise ValueError('Decimal exceeds numeric JSON precision; select CAST(value AS TEXT) for a lossless result')
    return f


def quote(name):return '"'+str(name).replace('"','""')+'"'


class SQLiteBusiness:
    def __init__(self,config):
        raw=config.get('path')
        if not raw or not Path(raw).is_absolute():raise ValueError('SQLite business path must be explicit and absolute')
        self.path=Path(raw).resolve(strict=True)
        if not self.path.is_file():raise ValueError('SQLite business database must already exist')
        with self.path.open('rb') as f:
            if f.read(16)!=b'SQLite format 3\x00':raise ValueError('Not an existing SQLite database')
        self.timeout=float(config.get('timeout',60))
        if self.timeout<=0:raise ValueError('SQLite query timeout must be positive')
        self.gate=asyncio.Semaphore(4)

    def connect(self):
        c=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=min(self.timeout,10))
        c.execute('PRAGMA query_only=ON')
        # No extension loading, ATTACH or writes through generated/user SQL.
        def authorize(action,arg1,arg2,db,source):
            if action in {sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_RECURSIVE}:return sqlite3.SQLITE_OK
            if action==sqlite3.SQLITE_FUNCTION and (arg2 or '').lower()!='load_extension':return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        return c,authorize

    async def run(self,fn):
        stop=threading.Event()
        async with self.gate:
            def work():
                c,auth=self.connect()
                deadline=time.monotonic()+self.timeout
                c.set_progress_handler(lambda:int(stop.is_set() or time.monotonic()>deadline),500)
                try:return fn(c,auth)
                except sqlite3.OperationalError as exc:
                    if 'interrupt' in str(exc).lower():raise TimeoutError('SQLite query timed out or cancelled') from exc
                    raise
                finally:c.close()
            task=asyncio.create_task(asyncio.to_thread(work))
            try:return await asyncio.shield(task)
            except asyncio.CancelledError:
                stop.set()
                try:await task
                except Exception:pass
                raise

    async def tables(self):
        return await self.run(lambda c,a:[r[0] for r in c.execute("SELECT name FROM sqlite_schema WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY name")])

    @staticmethod
    def catalog(c):
        out={}
        for (table,) in c.execute("SELECT name FROM sqlite_schema WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'"):
            out[table]=[{'name':r[1],'origin_type':r[2],'comment':None,'nullable':not bool(r[3]),'position':r[0]+1}
                        for r in c.execute('PRAGMA table_xinfo('+quote(table)+')') if r[6]!=1]
        return out

    async def columns(self,content,kind='table'):
        def work(c,auth):
            catalog=self.catalog(c)
            if kind.lower()=='table':
                key=next((t for t in catalog if t.lower()==content.lower()),None)
                if key is None:raise ValueError('Business table not found: '+content)
                return catalog[key]
            tree=select_sql(content,'sqlite')
            tree.set('limit',exp.Limit(expression=exp.Literal.number(0)))
            rewritten,decimal_labels=self.transform(c,tree,catalog)
            c.set_authorizer(auth)
            cursor=c.execute(render(rewritten,'sqlite'))
            infos={f['name'].lower():f for fs in catalog.values() for f in fs}
            select=tree
            while isinstance(select,exp.Union):select=select.this
            sources={table.alias_or_name.lower():{f['name'].lower():f for f in catalog.get(table.name,[])} for table in tree.find_all(exp.Table)}
            types={}
            for projection in select.expressions:
                expression=projection.this if isinstance(projection,exp.Alias) else projection
                column=next(expression.find_all(exp.Column),None)
                source=(sources.get(column.table.lower(),{}).get(column.name.lower(),{}) if column.table else infos.get(column.name.lower(),{})) if column else {}
                info={**source}
                if isinstance(expression,exp.Count):info['origin_type']='BIGINT'
                elif isinstance(expression,(exp.Sum,exp.Avg,exp.Add,exp.Sub,exp.Mul,exp.Div)):info['origin_type']='DECIMAL_TEXT'
                label=projection.alias if isinstance(projection,exp.Alias) else expression.name if isinstance(expression,exp.Column) else expression.sql(dialect='sqlite')
                if label.lower() in decimal_labels:info['origin_type']='DECIMAL_TEXT'
                types[label.lower()]=info
            return [{**{'origin_type':'','comment':None,'nullable':True},**infos.get(d[0].lower(),{}),**types.get(d[0].lower(),{}),'name':d[0],'position':i+1}
                    for i,d in enumerate(cursor.description)]
        return await self.run(work)

    def transform(self,c,tree,catalog):
        used={t.name.lower() for t in tree.find_all(exp.Table)}
        catalog={name:fs for name,fs in catalog.items() if name.lower() in used}
        decimal_columns={f['name'].lower() for fs in catalog.values() for f in fs if 'DECIMAL' in f['origin_type'].upper()}
        exact={f['name'].lower() for fs in catalog.values() for f in fs if 'DECIMAL' in f['origin_type'].upper() and 'TEXT' in f['origin_type'].upper()}
        # SQLite NUMERIC affinity can already round at insertion. Refuse approximate
        # storage for declared decimal columns; this cannot be repaired at query time.
        referenced={x.name.lower() for x in tree.find_all(exp.Column)}
        star=any(isinstance(x,exp.Star) for x in tree.walk())
        for table,fields in catalog.items():
            for f in fields:
                if f['name'].lower() in decimal_columns-exact and (star or f['name'].lower() in referenced):
                    if c.execute('SELECT 1 FROM '+quote(table)+' WHERE typeof('+quote(f['name'])+")='real' LIMIT 1").fetchone():
                        raise ValueError('SQLite REAL storage cannot prove exact DECIMAL input; use DECIMAL_TEXT or explicitly export the original source')
        def scalar(op):
            def call(a,b):
                if a is None or b is None:return None
                with localcontext() as ctx:
                    ctx.prec=100;ctx.traps[Inexact]=True;ctx.traps[Rounded]=True
                    result=op(number(a),number(b))
                    return str(result) if result is not None else None
            return call
        for name,op in [('decimal_add',lambda a,b:a+b),('decimal_sub',lambda a,b:a-b),('decimal_mul',lambda a,b:a*b),('decimal_div',lambda a,b:None if b==0 else a/b)]:
            c.create_function(name,2,scalar(op))
        c.create_function('decimal_cmp',2,lambda a,b:None if a is None or b is None else (number(a)>number(b))-(number(a)<number(b)))
        c.create_collation('DECIMAL',lambda a,b:(number(a)>number(b))-(number(a)<number(b)))
        for fn,kind in [('decimal_sum','sum'),('decimal_avg','avg'),('decimal_min','min'),('decimal_max','max')]:
            class Aggregate:
                def __init__(self):self.values=[]
                def step(self,value):
                    if value is not None:self.values.append(number(value))
                def finalize(self,kind=kind):
                    if not self.values:return None
                    with localcontext() as ctx:
                        ctx.prec=100;ctx.traps[Inexact]=True;ctx.traps[Rounded]=True
                        result=sum(self.values,Decimal(0)) if kind in ('sum','avg') else min(self.values) if kind=='min' else max(self.values)
                        if kind=='avg':result/=len(self.values)
                        return str(result)
            c.create_aggregate(fn,1,Aggregate)
        # Resolve decimal types by relation/scope before rewriting. Names alone
        # conflate JOIN columns and miss renamed CTE/subquery outputs.
        from sqlglot.optimizer.scope import traverse_scope,Scope
        decimal_nodes=set();scope_outputs={}
        scopes=list(traverse_scope(tree))
        for scope in scopes:
            sources={}
            for alias,source in scope.sources.items():
                if isinstance(source,exp.Table):
                    fields=next((fs for name,fs in catalog.items() if name.lower()==source.name.lower()),[])
                    sources[alias.lower()]={f['name'].lower():f['name'].lower() in exact and 'DECIMAL' in f['origin_type'].upper() and 'TEXT' in f['origin_type'].upper() for f in fields}
                elif isinstance(source,Scope):sources[alias.lower()]=scope_outputs.get(id(source),{})
            for column in scope.columns:
                matches=[sources.get(column.table.lower(),{})] if column.table else list(sources.values())
                if any(fields.get(column.name.lower()) for fields in matches):decimal_nodes.add(id(column))
            def is_decimal(expression):
                if isinstance(expression,exp.Cast):return False
                if isinstance(expression,exp.Column):return id(expression) in decimal_nodes
                if isinstance(expression,(exp.Count,exp.EQ,exp.NEQ,exp.GT,exp.GTE,exp.LT,exp.LTE,exp.Is)):return False
                return any(is_decimal(child) for child in expression.iter_expressions())
            projection=scope.expression
            if isinstance(projection,exp.Union):projection=projection.this
            output={}
            for i,expression in enumerate(projection.expressions):
                if isinstance(expression,exp.Star):
                    for fields in sources.values():output.update(fields)
                    continue
                name=(scope.outer_columns[i] if i<len(scope.outer_columns) else expression.alias_or_name or expression.sql(dialect='sqlite')).lower()
                output[name]=is_decimal(expression)
            scope_outputs[id(scope)]=output
            for key in ('order','group'):
                clause=scope.expression.args.get(key)
                if clause:
                    for column in clause.find_all(exp.Column):
                        if not column.table and output.get(column.name.lower()):decimal_nodes.add(id(column))
        numeric_aliases=set()
        def rewrite(node):
            if isinstance(node,exp.Cast):return node.copy(),False
            if isinstance(node,exp.Column):return node.copy(),id(node) in decimal_nodes
            cloned=node.copy();flags={}
            for key,value in node.args.items():
                if isinstance(value,exp.Expression):
                    rewritten,flag=rewrite(value)
                    cloned.set(key,rewritten);flags[key]=flag
                elif isinstance(value,list):
                    pairs=[rewrite(x) if isinstance(x,exp.Expression) else (x,False) for x in value]
                    cloned.set(key,[x for x,d in pairs]);flags[key]=any(d for x,d in pairs)
            dec=any(flags.values())
            if dec and isinstance(node,(exp.Add,exp.Sub,exp.Mul,exp.Div)):
                name={exp.Add:'decimal_add',exp.Sub:'decimal_sub',exp.Mul:'decimal_mul',exp.Div:'decimal_div'}[type(node)]
                args=[cloned.this,cloned.expression]
                args=[exp.Literal.string(a.this) if isinstance(a,exp.Literal) else a for a in args]
                return exp.Anonymous(this=name,expressions=args),True
            if dec and isinstance(node,(exp.Sum,exp.Avg,exp.Min,exp.Max)):
                return exp.Anonymous(this='decimal_'+node.key,expressions=[cloned.this]),True
            if dec and isinstance(node,(exp.EQ,exp.NEQ,exp.GT,exp.GTE,exp.LT,exp.LTE)):
                args=[cloned.this,cloned.expression]
                args=[exp.Literal.string(a.this) if isinstance(a,exp.Literal) else a for a in args]
                cmp=exp.Anonymous(this='decimal_cmp',expressions=args)
                return type(node)(this=cmp,expression=exp.Literal.number(0)),False
            if isinstance(node,exp.Select) and node.args.get('distinct'):
                selected=[]
                for before,after in zip(node.expressions,cloned.expressions):
                    if is_decimal(before):
                        value=after.this if isinstance(after,exp.Alias) else after
                        value=exp.Collate(this=value,expression=exp.Var(this='DECIMAL'))
                        after=exp.alias_(value,before.alias_or_name or before.sql(dialect='sqlite'),quoted=True)
                    selected.append(after)
                cloned.set('expressions',selected)
            if isinstance(node,exp.Group):
                cloned.set('expressions',[exp.Collate(this=a,expression=exp.Var(this='DECIMAL')) if is_decimal(before) else a for before,a in zip(node.expressions,cloned.expressions)])
            if dec and isinstance(node,exp.Ordered):
                cloned.set('this',exp.Collate(this=cloned.this,expression=exp.Var(this='DECIMAL')))
            if isinstance(node,exp.Alias) and dec:numeric_aliases.add(node.alias.lower())
            if isinstance(node,exp.Column) and dec:numeric_aliases.add(node.name.lower())
            return cloned,dec
        rewritten,_=rewrite(tree)
        selection=rewritten
        while isinstance(selection,exp.Union):selection=selection.this
        original=tree
        while isinstance(original,exp.Union):original=original.this
        # Preserve JDBC/SQLite output labels when precision rewrites change the
        # function name; DTO/chart keys must not become decimal_sum(...).
        projections=[]
        for before,after in zip(original.expressions,selection.expressions):
            if not isinstance(before,(exp.Alias,exp.Column,exp.Star)) and before.sql(dialect='sqlite')!=after.sql(dialect='sqlite'):
                after=exp.alias_(after,before.sql(dialect='sqlite'),quoted=True)
            projections.append(after)
        selection.set('expressions',projections)
        roots=scopes
        root_types=scope_outputs.get(id(roots[-1]),{}) if roots else {}
        numeric_aliases={k for k,v in root_types.items() if v}
        for projection in selection.expressions:
            expression=projection.this if isinstance(projection,exp.Alias) else projection
            if isinstance(expression,exp.Cast):
                numeric_aliases.discard(projection.alias_or_name.lower());continue
            if isinstance(expression,exp.Column) and root_types.get(projection.alias_or_name.lower()) or any(isinstance(f,exp.Anonymous) and f.name.lower().startswith('decimal_') and f.name.lower()!='decimal_cmp' for f in expression.walk()):
                numeric_aliases.add((projection.alias if isinstance(projection,exp.Alias) else expression.name if isinstance(expression,exp.Column) else expression.sql(dialect='sqlite')).lower())
        roots=scopes
        if roots:numeric_aliases.update(k for k,v in scope_outputs.get(id(roots[-1]),{}).items() if v)
        for projection in selection.expressions:
            if isinstance(projection,exp.Cast) or isinstance(projection,exp.Alias) and isinstance(projection.this,exp.Cast):
                numeric_aliases.discard(projection.alias_or_name.lower())
        return rewritten,numeric_aliases

    async def query(self,sql):
        tree=select_sql(sql,'sqlite')
        def work(c,auth):
            catalog=self.catalog(c);rewritten,decimals=self.transform(c,tree,catalog)
            c.set_authorizer(auth)
            executed=render(rewritten,'sqlite')
            cursor=c.execute(executed)
            keys=[d[0].lower() for d in cursor.description]
            rows=[{key:project(v) if key in decimals and v is not None else v for key,v in zip(keys,row)} for row in cursor]
            return {'dataList':rows,'dataSize':len(rows),'executedSql':executed}
        return await self.run(work)
