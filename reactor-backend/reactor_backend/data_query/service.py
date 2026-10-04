"""Schema recall → existing Tool NL2SQL → parsed business SQL → chart/table/files."""
import asyncio
import csv
import io
import json
import logging
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo
from reactor_backend.models.types import encode,Query
from reactor_backend.adapters.tool_stream import events
from reactor_backend.adapters.research_tools import ResearchTools
from reactor_backend.data_query.sql import resolve,select_sql,render

log=logging.getLogger(__name__)


class DataQuery:
    def __init__(self,catalog,db,api,settings):self.catalog,self.db,self.api,self.settings=catalog,db,api,settings
    async def prepare(self,query,trace=None,recall=True):
        models=await self.catalog.models()
        if not models:raise ValueError('问数模型为空，请检查 chat_model_info 表 yn=1 数据')
        rid=str(uuid4());date=datetime.now(ZoneInfo('Asia/Shanghai'))
        req={'requestId':rid,'query':query,'modelCodeList':[m['modelCode'] for m in models],'schemaInfo':models,
             'currentDateInfo':'当前时间信息：'+date.strftime('%Y-%m-%d')+','+['星期一','星期二','星期三','星期四','星期五','星期六','星期日'][date.weekday()],
             'traceId':trace or rid,'recallType':'only_recall','stream':True,'userInfo':'','dbType':self.db.type,
             'useVector':bool(self.settings.get('qdrant',{}).get('enable')),'useElastic':bool(self.settings.get('es',{}).get('enable'))}
        if recall and (req['useVector'] or req['useElastic']):
            selected=None
            for attempt in range(2):
                try:
                    response=await self.api.client.post(self.api.base_url+'/v1/tool/table_rag',json=req,headers=self.api.headers,timeout=120)
                    response.raise_for_status();payload=response.json()
                    if payload.get('code')!=200:raise ValueError('TableRAG error')
                    data=payload.get('data') or []
                    if isinstance(data,dict):data=list(data.values())
                    selected=[s for item in data for s in item.get('schemaList') or []]
                    break
                except asyncio.CancelledError:raise
                except Exception as exc:log.warning('TableRAG attempt %s failed (%s), schema fallback permitted by Java contract',attempt+1,type(exc).__name__)
            if selected:
                keys={(s['modelCode'],s['columnId']) for s in selected}
                for m in models:
                    for s in m.get('schemaList') or []:
                        if s.get('defaultRecall')==1 and (s['modelCode'],s['columnId']) not in keys:selected.append(s)
                    m['schemaList']=[s for s in selected if s['modelCode']==m['modelCode']] or None
            else:log.warning('TableRAG empty/unavailable: using existing DB schema (not synthetic schema)')
        return req
    async def generate(self,req,emit=None):
        body={**req,'stream':bool(emit)}
        if not emit:
            response=await self.api.client.post(self.api.base_url+'/v1/tool/nl2sql',json=body,headers=self.api.headers,timeout=600)
            response.raise_for_status();return response.json()
        result=None;done=False
        async with self.api.client.stream('POST',self.api.base_url+'/v1/tool/nl2sql',json=body,headers=self.api.headers,timeout=600) as response:
            async for event in events(response):
                if event is None:done=True;break
                if event.get('code') not in (None,200):raise ValueError('NL2SQL service failed')
                if event.get('status')=='nl2sql_think':await emit('THINK',event.get('nl2sql_think') or '')
                if event.get('status')=='finished_stream':await emit('finished_stream','finished_stream')
                if event.get('status')=='data':result=event
        if not done or result is None:raise ValueError('NL2SQL stream closed without SQL data')
        return result
    async def execute(self,req,result):
        if result.get('code')!=200 or not result.get('data'):raise ValueError('NL2SQL returned error or empty SQL')
        out=[]
        for row in result['data']:
            sql,columns,filters,dims,measures=resolve(row['nl2sql'],req['schemaInfo'],self.db.type)
            data=await self.db.query(sql)
            out.append({'question':row.get('query'),'dataList':data['dataList'],'columnList':columns,'filters':filters,
                'modelCode':None,'modelName':None,'loadSucceed':None,'errorMessage':None,'querySqlList':None,'limit':0,
                'dimCols':dims,'measureCols':measures,'nl2sqlResult':data.get('executedSql',sql),'id':None})
        return out
    async def query(self,query,trace=None,emit=None,visitor=None):
        req=await self.prepare(query,trace)
        req['visitorId']=visitor
        if getattr(self.api,'resources',None):
            if not visitor:raise ValueError('Missing trusted query owner')
            await self.api.resources.claim_new(visitor,'data_query',req['requestId'])
            await self.api.resources.namespace(visitor,req['requestId'])
        if emit:await emit('DEBUG',req['requestId'])
        data=await self.execute(req,await self.generate(req,emit))
        files=await self.export(req,data)
        return req,data,files
    async def export(self,req,data):
        q=Query(req['requestId'],req['requestId'],req.get('visitorId') or 'internal-data-query',req['query'],req['traceId'],'reactor',5)
        uploader=ResearchTools(self.api);files=[]
        for index,table in enumerate(data):
            rows=table['dataList'];cols=list(rows[0]) if rows else [c['guid'] for c in table['columnList']]
            buf=io.StringIO();writer=csv.DictWriter(buf,fieldnames=cols);writer.writeheader();writer.writerows(rows)
            files.append(await uploader.upload(q,f'query-{index+1}.csv',buf.getvalue(),'NL2SQL实际查询结果'))
            chart={'dataset':{'source':rows},'xAxis':{'type':'category'},'yAxis':{'type':'value'},
                'series':[{'type':'bar','encode':{'x':table['dimCols'][0] if table['dimCols'] else None,'y':m}} for m in table['measureCols']]}
            files.append(await uploader.upload(q,f'query-{index+1}-chart.json',encode(chart),'查询图表配置'))
        files.append(await uploader.upload(q,'query-provenance.json',encode({'requestId':req['requestId'],'traceId':req['traceId'],'query':req['query'],'dbType':self.db.type,'modelCodeList':req['modelCodeList'],
            'modelSources':[{'modelCode':m['modelCode'],'type':m['type'],'content':m['content']} for m in req['schemaInfo']],
            'executedSql':[t['nl2sqlResult'] for t in data],'files':files}), '查询来源与文件清单'))
        return files
    async def preview(self,code):
        models=await self.catalog.models();model=next((m for m in models if m['modelCode']==code),None)
        if not model:raise ValueError('模型不存在:'+code)
        from sqlglot import exp
        sql,_,_,_,_=resolve('SELECT * FROM `'+code.replace('`','``')+'`',models,self.db.type)
        tree=select_sql(sql,self.db.type);tree.set('limit',exp.Limit(expression=exp.Literal.number(100)))
        from reactor_backend.data_query.sql import DIALECTS
        return await self.db.query(render(tree,self.db.type))
    async def vector(self,req):
        cfg=self.settings.get('qdrant',{})
        if not cfg.get('enable'):return []
        response=await self.api.client.post(self.api.base_url+'/v1/tool/embedding/text',json={'inputs':[req['query']],'normalize':True},headers=self.api.headers)
        response.raise_for_status();vector=response.json()['vectors'][0]
        headers={'api-key':cfg['api_key']} if cfg.get('api_key') else {}
        body={'vector':vector,'filter':{'must':[{'key':'modelCode','match':{'any':req.get('modelCodeList') or []}}]},
              'limit':req.get('limit',100),'score_threshold':req.get('scoreThreshold',.5),'with_payload':True}
        response=await self.api.client.post(cfg['url'].rstrip('/')+'/collections/reactor_model_schema/points/search',json=body,headers=headers,timeout=req.get('timeout',50000)/1000)
        response.raise_for_status()
        return [{**p.get('payload',{}),'score':p['score'],'_id':str(p['id'])} for p in response.json()['result']]
    async def elastic(self,req):
        cfg=self.settings.get('es',{})
        if not cfg.get('enable'):return []
        body={'query':{'bool':{'filter':[{'terms':{'modelCode':req.get('modelCodeList') or []}}],'must':[{'match':{'value':req['query']}}]}},
              'sort':[{'_score':'desc'}],'size':req.get('limit',100)}
        response=await self.api.client.post(cfg['url'].rstrip('/')+'/reactor_model_column_value/_search',json=body,
            auth=(cfg.get('username',''),cfg.get('password','')) if cfg.get('username') else None)
        response.raise_for_status()
        return [{**h['_source'],'_score':h['_score']} for h in response.json()['hits']['hits']]
