"""Explicit business connections. Never reuses the ledger URL or initializes schema."""
import asyncio
import datetime
from decimal import Decimal
import httpx
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from reactor_backend.data_query.sql import select_sql


def value(v):
    # JDBC's DECIMAL remains numeric; temporal values keep their ISO text representation.
    if isinstance(v,Decimal):return float(v)
    if isinstance(v,(datetime.date,datetime.datetime,datetime.time)):return v.isoformat()
    if isinstance(v,bytes):return v.decode('utf-8',errors='replace')
    return v


class BusinessDB:
    def __init__(self,config,client):
        self.config,self.client=config,client;self.engine=None
        self.type=config.get('type','mysql').lower();self.gate=asyncio.Semaphore(4)
        if self.type=='mysql' and config.get('url'):
            if make_url(config['url']).drivername!='mysql+pymysql':raise ValueError('Business MySQL must explicitly use mysql+pymysql')
            self.engine=create_engine(config['url'],pool_size=4,max_overflow=0,pool_pre_ping=True,hide_parameters=True,
                connect_args={'connect_timeout':10,'read_timeout':config.get('timeout',60),'write_timeout':30})
        elif self.type=='sqlite':
            from reactor_backend.adapters.sqlite_business import SQLiteBusiness
            self.sqlite=SQLiteBusiness(config)
        elif self.type not in ('mysql','clickhouse','h2'):raise ValueError('Unsupported business DB')
    async def query(self,sql):
        select_sql(sql,self.type)
        if self.type=='sqlite':return await self.sqlite.query(sql)
        async with self.gate:
            if self.type=='mysql':
                if not self.engine:raise ValueError('Business MySQL connection not configured')
                def work():
                    with self.engine.connect() as c:
                        result=c.exec_driver_sql(sql);rows=[{str(k).lower():value(v) for k,v in row.items()} for row in result.mappings()]
                        return {'dataList':rows,'dataSize':len(rows)}
                task=asyncio.create_task(asyncio.to_thread(work))
                try:return await asyncio.shield(task)
                except asyncio.CancelledError:await task;raise
            if self.type=='clickhouse':
                if not self.config.get('url'):raise ValueError('Business ClickHouse connection not configured')
                response=await self.client.post(self.config['url'],content=sql+' FORMAT JSON',
                    auth=(self.config.get('username','default'),self.config.get('password','')),params={'database':self.config.get('schema','default')},timeout=self.config.get('timeout',60))
                response.raise_for_status();data=response.json()['data']
                return {'dataList':[{str(k).lower():v for k,v in r.items()} for r in data],'dataSize':len(data)}
            raise ValueError('H2 business role requires explicit SQLite configuration; original Java/H2 remains available for rollback')
    async def close(self):
        if self.engine:await asyncio.to_thread(self.engine.dispose)

    async def tables(self):
        if self.type=='sqlite':return await self.sqlite.tables()
        if self.type=='mysql':return [r['table_name'] for r in (await self.query('SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE()'))['dataList']]
        if self.type=='clickhouse':return [r['name'] for r in (await self.query('SELECT name FROM system.tables WHERE database=currentDatabase()'))['dataList']]
        raise ValueError('H2 business role is replaced by an explicitly configured SQLite source')

    async def columns(self,content,kind='table'):
        if self.type=='sqlite':return await self.sqlite.columns(content,kind)
        if self.type=='mysql' and kind.lower()=='table':
            from sqlglot import exp
            name=exp.Literal.string(content).sql(dialect='mysql')
            data=(await self.query('SELECT column_name AS name,data_type AS origin_type,column_comment AS comment,is_nullable AS nullable FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='+name+' ORDER BY ordinal_position'))['dataList']
            return data
        if self.type=='mysql' and kind.lower()=='sql':
            from reactor_backend.data_query.sql import render
            from sqlglot import exp
            from pymysql.constants import FIELD_TYPE
            tree=select_sql(content,'mysql');tree.set('limit',exp.Limit(expression=exp.Literal.number(0)))
            types={v:k for k,v in vars(FIELD_TYPE).items() if isinstance(v,int)}
            def work():
                with self.engine.connect() as c:
                    result=c.exec_driver_sql(render(tree,'mysql'))
                    return [{'name':d[0],'origin_type':types.get(d[1],''),'comment':None,'nullable':bool(d[6]),'position':i+1} for i,d in enumerate(result.cursor.description)]
            async with self.gate:return await asyncio.to_thread(work)
        if self.type=='clickhouse':
            from sqlglot import exp
            if kind.lower()=='table':
                name=exp.Literal.string(content).sql(dialect='clickhouse')
                return (await self.query('SELECT name,type AS origin_type,comment FROM system.columns WHERE database=currentDatabase() AND table='+name+' ORDER BY position'))['dataList']
            from reactor_backend.data_query.sql import render
            tree=select_sql(content,'clickhouse');tree.set('limit',exp.Limit(expression=exp.Literal.number(0)))
            if not self.config.get('url'):raise ValueError('Business ClickHouse connection not configured')
            response=await self.client.post(self.config['url'],content=render(tree,'clickhouse')+' FORMAT JSON',auth=(self.config.get('username','default'),self.config.get('password','')),params={'database':self.config.get('schema','default')},timeout=self.config.get('timeout',60))
            response.raise_for_status()
            return [{'name':d['name'],'origin_type':d['type'],'comment':None,'position':i+1} for i,d in enumerate(response.json()['meta'])]
        raise ValueError('Metadata discovery for this configured model requires an explicit supported catalog')
