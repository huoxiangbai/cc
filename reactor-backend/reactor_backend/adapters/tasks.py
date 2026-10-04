"""Session Todo, child definitions, background results and capability difference sets."""
from sqlalchemy import text
from reactor_backend.adapters.interactions import decoded, InteractionStore
from reactor_backend.models.types import encode


def task_view(r):
    return dict(id=r['task_id'],subject=r['subject'],description=r['description'],status=r['status'],
                activeForm=r.get('active_form'),owner=r.get('owner'),blocks=decoded(r.get('blocks_json'),[]),
                blockedBy=decoded(r.get('blocked_by_json'),[]),metadata=decoded(r.get('metadata_json'),{}))


def normalize_status(s):
    s=str(s or 'pending').strip().lower().replace('-','_')
    s={'done':'completed','inprogress':'in_progress'}.get(s,s)
    if s not in ('pending','in_progress','completed'):
        raise ValueError('非法 status: '+s)
    return s


class TaskStore(InteractionStore):
    async def todo(self, q, action, args):
        from reactor_backend.adapters.mysql import rows
        def work(c):
            self.authorize(c,q.visitor_id,q.session_id)
            # Session row also serializes concurrent child Todo mutations and high water assignment.
            rows(c,'SELECT id FROM ai_agent_dialogue_session WHERE session_id=:s AND deleted=0 FOR UPDATE',s=q.session_id)
            def load():
                return rows(c,'SELECT * FROM ai_agent_session_todo WHERE session_id=:s AND deleted=0 ORDER BY seq_no,id',s=q.session_id)
            old=load(); result={}
            def create(a, seq):
                subject=str(a.get('subject') or a.get('content') or a.get('description') or '').strip()
                desc=str(a.get('description') or subject).strip()
                if not subject or not desc:
                    raise ValueError('subject 与 description 必填')
                values=dict(s=q.session_id,t=str(seq),seq=seq,subject=subject,description=desc,
                            active=a.get('activeForm') or None,status=normalize_status(a.get('status')),metadata=encode(a.get('metadata') or {}))
                c.execute(text("""INSERT INTO ai_agent_session_todo(session_id,task_id,seq_no,subject,description,active_form,status,metadata_json)
                    VALUES(:s,:t,:seq,:subject,:description,:active,:status,:metadata)
                    ON DUPLICATE KEY UPDATE subject=VALUES(subject),description=VALUES(description),active_form=VALUES(active_form),status=VALUES(status),metadata_json=VALUES(metadata_json),owner=NULL,blocks_json=NULL,blocked_by_json=NULL"""),values)
                return dict(id=str(seq),subject=subject,status=values['status'])
            if action=='TaskCreate':
                if not str(args.get('subject') or '').strip() or not str(args.get('description') or '').strip():
                    raise ValueError('subject 与 description 必填')
                seq=rows(c,'SELECT COALESCE(MAX(seq_no),0)+1 AS n FROM ai_agent_session_todo WHERE session_id=:s',s=q.session_id)[0]['n']
                result={'task':create(args,seq),'message':'已创建任务 #'+str(seq)}
            elif action=='TaskUpdate':
                item=next((r for r in old if r['task_id']==str(args.get('taskId') or '').strip()),None)
                if item is None:
                    result={'ok':False,'taskId':args.get('taskId'),'message':'Task not found'}
                elif args.get('status')=='deleted':
                    # Removing a row is the original Todo deletion operation, never a database reset.
                    c.execute(text('DELETE FROM ai_agent_session_todo WHERE id=:id'),{'id':item['id']})
                    result={'deleted':True,'taskId':item['task_id']}
                else:
                    view=task_view(item)
                    for key in ('subject','description','activeForm','owner'):
                        if key in args and (key!='subject' or str(args[key] or '').strip()):view[key]=args[key]
                    if args.get('status'):view['status']=normalize_status(args['status'])
                    for source,key in (('addBlocks','blocks'),('addBlockedBy','blockedBy')):
                        for v in args.get(source) or []:
                            v=str(v).strip()
                            if v and v not in view[key]:view[key].append(v)
                    c.execute(text('UPDATE ai_agent_session_todo SET subject=:subject,description=:description,active_form=:activeForm,owner=:owner,status=:status,blocks_json=:blocks,blocked_by_json=:blockedBy WHERE id=:row'),{**view,'blocks':encode(view['blocks']),'blockedBy':encode(view['blockedBy']),'row':item['id']})
                    result={'success':True,'task':view,'message':'已更新任务 #'+item['task_id']}
            elif action=='TodoWrite':
                if not isinstance(args.get('todos'),list):raise ValueError('todos 必须为数组')
                todos=[a for a in args['todos'] if isinstance(a,dict)]
                # Validate the entire replacement before mutating it.
                for a in todos:normalize_status(a.get('status'))
                c.execute(text('DELETE FROM ai_agent_session_todo WHERE session_id=:s'),{'s':q.session_id})
                if not all(normalize_status(a.get('status'))=='completed' for a in todos):
                    for index,a in enumerate(todos,1):
                        if a.get('content') or a.get('subject') or a.get('description'):create(a,index)
                result={'oldCount':len(old),'message':'Todos have been modified successfully. Continue using the todo list to track progress.'}
            elif action=='TaskGet':
                item=next((r for r in old if r['task_id']==str(args.get('taskId') or '').strip()),None)
                result={'task':task_view(item)} if item else {'ok':False,'taskId':args.get('taskId'),'message':'Task not found'}
            elif action!='TaskList':
                raise ValueError('Unknown Todo action')
            tasks=[task_view(r) for r in load()]
            snapshot=dict(listId=q.session_id,tasks=tasks,total=len(tasks),pending=sum(t['status']=='pending' for t in tasks),
                          inProgress=sum(t['status']=='in_progress' for t in tasks),completed=sum(t['status']=='completed' for t in tasks))
            if action=='TaskList':result={'tasks':[{k:t[k] for k in ('id','subject','status')} for t in tasks],'total':len(tasks)}
            if action=='TodoWrite':result.update(newCount=len(tasks),tasks=tasks)
            return {'tool':action,'ok':True,**result},snapshot
        return await self.transact(work)

    async def child_definition(self, name):
        from reactor_backend.adapters.mysql import rows
        name=(name or 'general-purpose').strip()
        if name=='general-purpose':
            return dict(agent_key=name,system_prompt='Execute only this self-contained task. You cannot see the coordinator conversation. Deliver verified results with workspace paths.',allowed_tools_json=['*'],disallowed_tools_json=[],max_steps=200)
        rs=await self.transact(lambda c:rows(c,'SELECT * FROM ai_agent_sub_agent_definition WHERE agent_key=:n AND status=1 AND deleted=0',n=name))
        if not rs:raise ValueError('未知或禁用 subagent_type: '+name)
        return rs[0]

    async def background_create(self, q, task):
        def work(c):
            self.authorize(c,q.visitor_id,q.session_id)
            c.execute(text('''INSERT INTO ai_agent_background_task(session_id,task_id,type,status,description,agent_id,agent_type,prompt,started_at_ms)
                VALUES(:session_id,:task_id,:type,:status,:description,:agent_id,:agent_type,:prompt,:started_at_ms)'''),task)
        await self.transact(work)

    async def background_get(self, q, task_id=None, agent_id=None):
        from reactor_backend.adapters.mysql import rows
        def work(c):
            self.authorize(c,q.visitor_id,q.session_id)
            return rows(c,'SELECT * FROM ai_agent_background_task WHERE session_id=:s AND '+('task_id=:t' if task_id else 'agent_id=:t')+' AND deleted=0 ORDER BY create_time DESC,id DESC',s=q.session_id,t=task_id or agent_id)
        rs=await self.transact(work)
        return rs[0] if rs else None

    async def background_settle(self, session, task_id, status, output=None, error=None, tools=0, duration=0):
        from time import time
        return await self.transact(lambda c:c.execute(text('''UPDATE ai_agent_background_task SET status=:status,output=:output,error_msg=:error,total_tool_use_count=:tools,total_duration_ms=:duration,ended_at_ms=:at
            WHERE session_id=:s AND task_id=:t AND status='running' AND deleted=0'''),dict(status=status,output=output,error=error,tools=tools,duration=duration,at=int(time()*1000),s=session,t=task_id)).rowcount)

    async def capabilities(self, visitor, session, toggle=None):
        from reactor_backend.adapters.mysql import rows
        def work(c):
            self.authorize(c,visitor,session)
            if toggle:
                kind=str(toggle.get('kind') or '').strip().lower();ref=str(toggle.get('refId') or '').strip()
                if kind not in ('skill','mcp') or not ref or not isinstance(toggle.get('enabled'),bool):raise ValueError('kind/refId/enabled 非法')
                c.execute(text('INSERT INTO ai_agent_session_capability(session_id,kind,ref_id,enabled) VALUES(:s,:k,:r,:e) ON DUPLICATE KEY UPDATE enabled=VALUES(enabled)'),dict(s=session,k=kind,r=ref,e=int(toggle['enabled'])))
            return rows(c,'SELECT kind,ref_id,enabled FROM ai_agent_session_capability WHERE session_id=:s',s=session)
        return await self.transact(work)

    async def mcp_capabilities(self):
        from reactor_backend.adapters.mysql import rows
        return await self.transact(lambda c:rows(c,"SELECT mcp_id AS refId,mcp_name AS name FROM ai_client_tool_mcp WHERE status=1 ORDER BY id"))
