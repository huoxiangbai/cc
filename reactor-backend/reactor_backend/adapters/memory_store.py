"""Original curated/fork/compaction tables, visitor ownership and projection search."""
from sqlalchemy import text
from reactor_backend.models.types import encode
from reactor_backend.memory.working import tokens, normalize_call


class MemoryStore:
    async def enabled_mcps(self):
        from reactor_backend.adapters.mysql import rows
        return await self.transact(lambda c:rows(c,'SELECT * FROM ai_client_tool_mcp WHERE status=1 ORDER BY id'))

    async def memory_entries(self, query, target=None):
        from reactor_backend.adapters.mysql import rows
        def work(c):
            self._owner(c,query.visitor_id,query.session_id)
            return rows(c,"SELECT * FROM ai_agent_ltm_curated_entry WHERE owner_type='VISITOR' AND owner_id=:v AND deleted=0 AND status='ACTIVE'"+(' AND scope=:target' if target else '')+' ORDER BY id',v=query.visitor_id,target=target)
        return await self.transact(work)

    async def memory_mutate(self, query, args, origin='assistant_tool'):
        from reactor_backend.adapters.mysql import rows,insert
        def work(c):
            self._owner(c,query.visitor_id,query.session_id)
            # Lock the persistent visitor for capacity checks across sessions/forks.
            rows(c,'SELECT id FROM ai_agent_visitor_identity WHERE visitor_id=:v AND deleted=0 FOR UPDATE',v=query.visitor_id)
            scope=str(args.get('target') or 'curated').lower()
            if scope not in ('curated','user'):raise ValueError('Unknown memory target')
            entries=rows(c,"SELECT * FROM ai_agent_ltm_curated_entry WHERE owner_type='VISITOR' AND owner_id=:v AND scope=:s AND deleted=0 AND status='ACTIVE' ORDER BY id FOR UPDATE",v=query.visitor_id,s=scope)
            measure=lambda values:len('\n§\n'.join(e['content'] for e in values).encode('utf-16-le'))//2
            used=measure(entries); limit=1375 if scope=='user' else 2200
            action=str(args.get('action') or '').lower(); content=str(args.get('content') or '').strip();old=str(args.get('old_text') or '').strip()
            result=lambda ok,msg:dict(success=ok,staged=False,no_change=msg=='duplicate entry',message=msg,used_chars=used,limit_chars=limit)
            if action=='add':
                if not content:return result(False,'content required')
                if any(e['content']==content for e in entries):return result(True,'duplicate entry')
                trial=entries+[{'content':content}]
                if measure(trial)>limit:return result(False,f'memory full ({used}/{limit}); consolidate entries before adding')
                insert(c,'ltm_curated_entry',dict(owner_type='VISITOR',owner_id=query.visitor_id,scope=scope,content=content,status='ACTIVE',source_session_id=query.session_id,source_request_id=query.request_id[:64],write_origin=origin))
                used=measure(trial);return result(True,'added')
            if action not in ('replace','remove'):return result(False,'unknown action: '+action)
            if not old or action=='replace' and not content:return result(False,'old_text and content required')
            matches=[e for e in entries if old in e['content']]
            if len(matches)!=1:return result(False,'no entry matched old_text' if not matches else 'old_text matches multiple entries; be more specific')
            target=matches[0]; trial=[{'content':content} if e['id']==target['id'] else e for e in entries] if action=='replace' else [e for e in entries if e['id']!=target['id']]
            if measure(trial)>limit:return result(False,'replace would exceed capacity')
            if action=='remove':c.execute(text("UPDATE ai_agent_ltm_curated_entry SET deleted=1,status='DELETED' WHERE id=:id"),{'id':target['id']})
            else:c.execute(text('UPDATE ai_agent_ltm_curated_entry SET content=:content,source_session_id=:session,source_request_id=:request,write_origin=:origin WHERE id=:id'),dict(content=content,session=query.session_id,request=query.request_id[:64],origin=origin,id=target['id']))
            used=measure(trial);return result(True,'removed' if action=='remove' else 'replaced')
        return await self.transact(work)

    async def fork_event(self,query,event):
        from reactor_backend.adapters.mysql import insert
        return await self.transact(lambda c:insert(c,'ltm_fork_execution',dict(session_id=query.session_id,trigger_request_id=query.request_id[:64],owner_type='VISITOR',owner_id=query.visitor_id,**event)))

    def replace_projection(self,c,run,messages,scope='main'):
        from reactor_backend.adapters.mysql import rows
        from uuid import uuid4
        rows(c,'SELECT id FROM ai_agent_dialogue_session WHERE session_id=:s AND deleted=0 FOR UPDATE',s=run['session_id'])
        alias='subagent:'+scope[4:] if scope.startswith('sub:') else scope
        source=rows(c,'SELECT * FROM ai_agent_working_memory_message WHERE session_id=:s AND memory_scope IN (:scope,:alias) AND deleted=0 ORDER BY id',s=run['session_id'],scope=scope,alias=alias)
        import json
        def identity(m):
            calls=m.get('tool_calls') or []
            return (m['role'],m.get('tool_call_id')) if m['role']=='tool' else (m['role'],tuple(call['id'] for call in calls)) if calls else (m['role'],json.dumps(m.get('content'),ensure_ascii=False,sort_keys=True),m.get('_base64_image'))
        origins={}
        for r in source:
            raw=r.get('tool_calls_json');calls=json.loads(raw) if isinstance(raw,str) else raw
            key=identity(dict(role=r['role'].lower(),content=r['content'],tool_call_id=r['tool_call_id'],tool_calls=calls,_base64_image=r.get('base64_image')))
            origins.setdefault(key,r['origin_message_key'])
        messages=[{**m,'_origin':origins.get(identity(m))} for m in messages]
        c.execute(text('UPDATE ai_agent_working_memory_turn SET status=2 WHERE session_id=:s AND memory_scope IN (:scope,:alias) AND status=1 AND deleted=0'),dict(s=run['session_id'],scope=scope,alias=alias))
        synthetic={**run,'request_id':'wm-compact-'+uuid4().hex}
        self._save_context(c,synthetic,messages,scope)
        return synthetic['request_id']

    async def session_search(self,query,args):
        from reactor_backend.adapters.mysql import rows
        import re
        terms=list(dict.fromkeys(re.findall(r'[^\W_]+',str(args.get('query') or '').lower(),re.UNICODE)))
        sid=args.get('session_id');anchor=args.get('around_message_id');scope=args.get('scope','user')
        limit=int(args.get('limit',8));window=int(args.get('window',5))
        if limit<1:raise ValueError('limit must be >= 1')
        if terms and anchor is not None:raise ValueError('query cannot be combined with around_message_id')
        if anchor is not None and (not sid or window<1):raise ValueError('session_id and positive window required for scroll')
        if terms and scope=='session' and not sid:sid=query.session_id
        roles=list(dict.fromkeys(r.strip().upper() for r in str(args.get('role_filter') or 'user,assistant').split(',') if r.strip().upper() in ('USER','ASSISTANT','TOOL','SYSTEM')))
        if not roles:roles=['USER','ASSISTANT']
        role_filter=','.join(roles)
        def work(c):
            self._owner(c,query.visitor_id,query.session_id)
            if sid:self._owner(c,query.visitor_id,sid)
            if terms:
                filters="m.session_id=:s" if sid else "s.visitor_id=:v AND (m.session_id<>:current OR t.status=2)"
                role_sql=','.join("'"+role+"'" for role in roles)
                base=" FROM ai_agent_working_memory_message m JOIN ai_agent_working_memory_turn t ON t.id=m.turn_id JOIN ai_agent_dialogue_session s ON s.session_id=m.session_id WHERE m.memory_scope='main' AND m.deleted=0 AND t.deleted=0 AND s.deleted=0 AND t.status IN (1,2) AND m.role IN ("+role_sql+") AND "+filters
                params=dict(s=sid,v=query.visitor_id,current=query.session_id,q=args.get('query'),pattern='%'+str(args.get('query') or '')+'%',n=min(100,limit*4))
                try:
                    raw=rows(c,"SELECT m.*,s.title,s.started_at,s.last_active_at,MATCH(m.content) AGAINST (:q IN NATURAL LANGUAGE MODE) AS search_score"+base+" AND MATCH(m.content) AGAINST (:q IN NATURAL LANGUAGE MODE) ORDER BY search_score DESC,t.turn_seq DESC,m.seq_no DESC,m.id DESC LIMIT :n",**params)
                    backend='fulltext'
                except Exception:
                    raw=rows(c,"SELECT m.*,s.title,s.started_at,s.last_active_at"+base+" AND m.content LIKE :pattern ORDER BY t.turn_seq DESC,m.seq_no DESC,m.id DESC LIMIT :n",**params)
                    backend='scan'
                found=[];seen=set()
                for r in raw:
                    content=r['content'] or '';key=(r['session_id'],r['origin_message_key'])
                    if key in seen or not all(t in content.lower() for t in terms) or content.lstrip().startswith(('[CONTEXT COMPACTION','[CONTEXT SUMMARY]:','[COMPACTION SUMMARY]','[WM_COMPACTION_SUMMARY]')):continue
                    seen.add(key)
                    match=next((content.lower().find(t) for t in [str(args.get('query') or '').lower()]+terms if content.lower().find(t)>=0),-1)
                    start=max(0,match-100) if len(content)>280 and match>=0 else 0;end=min(len(content),start+280)
                    item=dict(session_id=r['session_id'],match_message_id=r['id'],origin_message_key=r['origin_message_key'],stable_key=f"{r['session_id']}:{r['request_id']}:{r['seq_no']}",matched_role=r['role'],snippet=('...' if start else '')+content[start:end]+('...' if end<len(content) else ''),matched_terms=terms)
                    if 'search_score' in r:item['search_score']=float(r['search_score'])
                    item.update({k:v.isoformat(sep=' ') if hasattr(v,'isoformat') else v for k,v in r.items() if k in ('title','started_at','last_active_at')})
                    found.append(item)
                    if len(found)>=min(limit,20):break
                return dict(tool='session_search',ok=True,mode='discover',query=args.get('query'),role_filter=role_filter,results=found,count=len(found),search_backend=backend)
            sessions=rows(c,'SELECT * FROM ai_agent_dialogue_session WHERE visitor_id=:v AND deleted=0'+(' AND session_id=:s' if sid else '')+' ORDER BY last_active_at DESC,id DESC',v=query.visitor_id,s=sid)
            found=[]
            for session in sessions:
                source=rows(c,"SELECT m.*,t.status AS turn_status FROM ai_agent_working_memory_message m JOIN ai_agent_working_memory_turn t ON t.id=m.turn_id WHERE m.session_id=:s AND m.memory_scope='main' AND m.deleted=0 AND t.deleted=0 AND t.status IN (1,2) ORDER BY t.turn_seq,m.seq_no",s=session['session_id'])
                # Deduplicate originals and later projection copies by the original identity.
                seen=set();visible=[]
                for r in source:
                    key=r['origin_message_key'];content=r['content'] or ''
                    if key in seen or r['role'] not in roles or content.lstrip().startswith(('[CONTEXT COMPACTION','[CONTEXT SUMMARY]:','[COMPACTION SUMMARY]','[WM_COMPACTION_SUMMARY]')):continue
                    seen.add(key);visible.append(r)
                def shape(r):
                    content=r['content'] or ''
                    value=dict(id=r['id'],stable_key=f"{r['session_id']}:{r['request_id']}:{r['seq_no']}",role=r['role'],content=content[:4000]+('...' if len(content)>4000 else ''),seq_no=r['seq_no'])
                    if len(content)>4000:value.update(content_truncated=True,original_content_chars=len(content))
                    if anchor is not None and r['id']==int(anchor):value['anchor']=True
                    return value
                metadata={k:session.get(k) for k in ('title','started_at','last_active_at')}
                metadata={k:v.isoformat(sep=' ') if hasattr(v,'isoformat') else v for k,v in metadata.items()}
                if sid and not terms:
                    if anchor is not None:
                        idx=next((i for i,m in enumerate(visible) if m['id']==int(anchor)),None)
                        if idx is None:raise ValueError('Anchor does not exist in visible session history')
                        n=min(window,20);selected=visible[max(0,idx-n):idx+n+1]
                        return dict(tool='session_search',ok=True,mode='scroll',session_id=sid,around_message_id=anchor,window=n,role_filter=role_filter,messages=[shape(r) for r in selected],messages_before=min(n,idx),messages_after=min(n,len(visible)-idx-1),**metadata)
                    # Preserve Java's first-20 rule (21–30-message histories also show first 20).
                    truncated=len(visible)>30;selected=visible[:20]+visible[-10:] if truncated else visible[:20]
                    result=dict(tool='session_search',ok=True,mode='read',session_id=sid,role_filter=role_filter,messages=[shape(r) for r in selected],truncated=truncated,message_count=len(visible),**metadata)
                    if truncated:result['message']=f'Session has {len(visible)} visible messages; showing first 20 + last 10. Pass around_message_id (any id above) to scroll the middle.'
                    return result
                if session['session_id']==query.session_id:continue
                found.append(dict(session_id=session['session_id'],title=session['title'],preview=session.get('latest_query_text') or session.get('latest_summary_text'),started_at=metadata['started_at'],last_active_at=metadata['last_active_at'],message_count=len(visible)))
                if len(found)>=min(limit,20):break
            result=dict(tool='session_search',ok=True,mode='browse',results=found,count=len(found))
            return result
        return await self.transact(work)
