"""Read the existing chat_model_info/schema tables, with original distinct semantics."""
from reactor_backend.adapters.mysql import rows


def camel(key):
    first,*tail=key.split('_');return first+''.join(x.title() for x in tail)


class DataCatalog:
    def __init__(self,ledger):self.ledger=ledger
    async def models(self):
        def work(c):
            records=rows(c,'SELECT * FROM chat_model_info WHERE yn=1 ORDER BY id DESC');schemas=rows(c,'SELECT * FROM chat_model_schema WHERE yn=1 ORDER BY id DESC')
            seen=set();fields=[]
            for s in schemas:
                key=(s['model_code'],s['column_id'])
                if key in seen:continue
                dto_keys={'modelCode','columnId','columnName','columnComment','fewShot','dataType','synonyms','vectorUuid','defaultRecall','analyzeSuggest'}
                seen.add(key);fields.append({camel(k):v for k,v in s.items() if camel(k) in dto_keys})
            seen=set();out=[]
            for m in records:
                if m['code'] in seen:continue
                seen.add(m['code']);out.append({'modelCode':m['code'],'modelName':m['name'],'usePrompt':m['use_prompt'],
                    'businessPrompt':m['business_prompt'],'type':m['type'],'content':m['content'],
                    'schemaList':[s for s in fields if s['modelCode']==m['code']] or None})
            return out
        return await self.ledger.transact(work)

    async def initialize(self,db,api,config):
        """Original idempotent model init and explicit refresh, without DDL/DROP."""
        definitions=config.get('modelList') or []
        if not definitions:return
        current=await self.models();force=bool(config.get('forceRefresh'))
        if not force and all(any(m['modelCode']==d['id'] and m.get('schemaList') for m in current) for d in definitions):return
        from sqlglot import exp
        from reactor_backend.data_query.sql import select_sql,DIALECTS,render
        from reactor_backend.adapters.sqlite_business import quote
        from uuid import uuid4
        import json
        planned=[]
        for model in definitions:
            if not model.get('id') or len(model['id'])>50:raise ValueError('Invalid model code')
            fields=await db.columns(model['content'],model['type'])
            raw='SELECT * FROM '+quote(model['content']) if model['type'].lower()=='table' else model['content']
            tree=select_sql(raw,db.type);tree.set('limit',exp.Limit(expression=exp.Literal.number(10000)))
            sample=(await db.query(render(tree,db.type)))['dataList']
            def names(key):return set(filter(None,(model.get(key) or '').split(',')))
            aliases=model.get('columnAliasMap') or {}
            if isinstance(aliases,str):aliases=json.loads(aliases)
            schemas=[]
            for field in fields:
                name=field['name']
                if name in names('ignoreFields'):continue
                origin=(field.get('origin_type') or '').upper()
                dtype='DATE' if any(t in origin for t in ('DATE','TIME')) else 'DECIMAL' if any(t in origin for t in ('INT','FLOAT','DOUBLE','REAL','NUMERIC','DECIMAL')) else 'VARCHAR'
                values=[]
                for row in sample:
                    value=row.get(name.lower())
                    if value is not None and str(value).strip():
                        value=str(value)[:300]
                        if value not in values and len(values)<12:values.append(value)
                def enabled(key):return name.lower() in {x.lower() for x in names(key)}
                schemas.append({'modelCode':model['id'],'columnId':name,'columnName':field.get('comment') or name,
                    'columnComment':field.get('comment') or name,'fewShot':','.join(values) or None,'dataType':dtype,
                    'synonyms':aliases.get(name.lower(),aliases.get(name.upper())),'vectorUuid':','.join(str(uuid4()) for _ in range(4)),
                    'defaultRecall':int(enabled('defaultRecallFields')),'analyzeSuggest':-1 if enabled('analyzeForbidFields') else int(enabled('analyzeSuggestFields'))})
            if not schemas:raise ValueError('Model has no usable schema: '+model['id'])
            planned.append((model,schemas))
        await self.sync_indexes(db,api,config,planned)
        from sqlalchemy import text
        def save(c):
            if force:
                active={d['id'] for d in definitions}
                for old in rows(c,'SELECT code FROM chat_model_info WHERE yn=1'):
                    if old['code'] not in active:
                        for table in ('chat_model_info','chat_model_schema'):
                            column='code' if table=='chat_model_info' else 'model_code'
                            c.execute(text('UPDATE '+table+' SET yn=0 WHERE '+column+'=:code'),dict(code=old['code']))
            for model,schemas in planned:
                # Atomic replacement of active projections; prior rows retained for rollback.
                for table,column in [('chat_model_info','code'),('chat_model_schema','model_code')]:
                    c.execute(text('UPDATE '+table+' SET yn=0 WHERE '+column+'=:code'),dict(code=model['id']))
                c.execute(text('INSERT INTO chat_model_info(code,type,name,content,use_prompt,business_prompt) VALUES(:id,:type,:name,:content,:remark,:businessPrompt)'),
                    {**model,'name':model.get('name'),'remark':model.get('remark'),'businessPrompt':model.get('businessPrompt')})
                for s in schemas:
                    c.execute(text('INSERT INTO chat_model_schema(model_code,column_id,column_name,column_comment,few_shot,data_type,synonyms,vector_uuid,default_recall,analyze_suggest) VALUES(:modelCode,:columnId,:columnName,:columnComment,:fewShot,:dataType,:synonyms,:vectorUuid,:defaultRecall,:analyzeSuggest)'),s)
        await self.ledger.transact(save)

    async def sync_indexes(self,db,api,config,planned):
        """Real optional schema-vector and column-value indexing; failures propagate."""
        import json
        from datetime import datetime
        from reactor_backend.adapters.sqlite_business import quote
        q=config.get('qdrant',{});es=config.get('es',{})
        collection='reactor_model_schema';index='reactor_model_column_value'
        retained={m['id'] for m,s in planned}
        retired=[m['modelCode'] for m in await self.models() if m['modelCode'] not in retained] if config.get('forceRefresh') else []
        if q.get('enable'):
            root=q['url'].rstrip('/');headers={'api-key':q['api_key']} if q.get('api_key') else {}
            r=await api.client.get(root+'/collections/'+collection,headers=headers);exists=r.status_code!=404
            if exists:r.raise_for_status()
            for model,schemas in planned:
                texts=[];points=[]
                for s in schemas:
                    for i,key in enumerate(('columnName','synonyms','columnComment','fewShot')):
                        if key=='fewShot' and s['dataType']=='DECIMAL':continue
                        if s.get(key):
                            texts.append(s[key]);points.append({'id':s['vectorUuid'].split(',')[i],'payload':s})
                if not texts:continue
                r=await api.client.post(api.base_url+'/v1/tool/embedding/text',json={'inputs':texts,'normalize':True},headers=api.headers);r.raise_for_status()
                vectors=r.json()['vectors']
                if len(vectors)!=len(points):raise ValueError('Embedding count mismatch')
                if not exists:
                    r=await api.client.put(root+'/collections/'+collection,json={'vectors':{'size':len(vectors[0]),'distance':'Cosine'}},headers=headers);r.raise_for_status();exists=True
                r=await api.client.post(root+'/collections/'+collection+'/points/delete',json={'filter':{'must':[{'key':'modelCode','match':{'value':model['id']}}]}},params={'wait':'true'},headers=headers);r.raise_for_status()
                for p,v in zip(points,vectors):p['vector']=v
                r=await api.client.put(root+'/collections/'+collection+'/points',json={'points':points},params={'wait':'true'},headers=headers);r.raise_for_status()
            if exists and retired:
                r=await api.client.post(root+'/collections/'+collection+'/points/delete',json={'filter':{'must':[{'key':'modelCode','match':{'any':retired}}]}},params={'wait':'true'},headers=headers);r.raise_for_status()
        if es.get('enable'):
            root=es['url'].rstrip('/');auth=(es.get('username',''),es.get('password','')) if es.get('username') else None
            r=await api.client.head(root+'/'+index,auth=auth)
            if r.status_code==404:
                mapping={'mappings':{'properties':{k:{'type':'keyword' if k in ('modelCode','columnId','valueId') else 'text'} for k in ('modelCode','columnId','valueId','value','columnName','columnComment','synonyms','dataType')}}}
                r=await api.client.put(root+'/'+index,json=mapping,auth=auth)
            r.raise_for_status()
            for model,schemas in planned:
                selected={x.lower() for x in (model.get('syncValueFields') or '').split(',')}
                source=quote(model['content']) if model['type'].lower()=='table' else '('+model['content']+') t'
                lines=[]
                for s in schemas:
                    if s['columnId'].lower() not in selected:continue
                    col=quote(s['columnId'])
                    from reactor_backend.data_query.sql import select_sql,render
                    result=await db.query(render(select_sql('SELECT '+col+' AS value FROM '+source+' WHERE '+col+' IS NOT NULL GROUP BY '+col+' LIMIT 10000',db.type),db.type))
                    for row in result['dataList']:
                        value=str(row['value']);vid=model['id']+s['columnId']+value
                        lines.extend([json.dumps({'index':{'_index':index,'_id':vid}}),json.dumps({**s,'value':value,'valueId':vid,'createTime':datetime.now().isoformat()})])
                r=await api.client.post(root+'/'+index+'/_delete_by_query',json={'query':{'term':{'modelCode':model['id']}}},params={'refresh':'true'},auth=auth);r.raise_for_status()
                if lines:
                    r=await api.client.post(root+'/_bulk',content='\n'.join(lines)+'\n',headers={'Content-Type':'application/x-ndjson'},auth=auth);r.raise_for_status()
                    if r.json().get('errors'):raise ValueError('ES column value sync failed')
            if retired:
                r=await api.client.post(root+'/'+index+'/_delete_by_query',json={'query':{'terms':{'modelCode':retired}}},params={'refresh':'true'},auth=auth);r.raise_for_status()
