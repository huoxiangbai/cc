"""Fail without replay only under a declared exclusive startup recovery window."""
from sqlalchemy import text


async def recover(ledger):
    def work(c):
        counts={}
        counts['runs']=c.execute(text("UPDATE ai_agent_dialogue_run SET status=2,error_code='PROCESS_RESTART',error_msg='interrupted by process restart',finished_at=NOW(3) WHERE status=0 AND deleted=0")).rowcount
        for kind in ('llm','tool'):
            # All RUNNING calls are orphaned in this declared exclusive window,
            # including background calls whose root already committed SUCCESS.
            counts[kind]=c.execute(text(f"UPDATE ai_agent_{kind}_invocation i JOIN ai_agent_dialogue_run r ON r.id=i.run_id SET i.status=2,i.error_msg='interrupted by process restart',i.finished_at=NOW(3) WHERE i.status=0 AND i.deleted=0 AND r.deleted=0")).rowcount
        counts['background']=c.execute(text("UPDATE ai_agent_background_task SET status='failed',error_msg='interrupted by process restart',ended_at_ms=UNIX_TIMESTAMP(NOW(3))*1000 WHERE status='running' AND deleted=0")).rowcount
        counts['receipts']=c.execute(text('''UPDATE ai_agent_tool_invocation i JOIN ai_agent_dialogue_run r ON r.id=i.run_id
            JOIN ai_agent_background_task b ON b.session_id=r.session_id AND b.task_id=JSON_UNQUOTE(JSON_EXTRACT(IF(JSON_VALID(i.llm_oberserve),i.llm_oberserve,'{}'),'$.task_id'))
            SET i.llm_oberserve=JSON_SET(i.llm_oberserve,'$.ok',CAST('false' AS JSON),'$.status','failed','$.error',b.error_msg,'$.message',CONCAT('任务失败：',b.error_msg))
            WHERE i.tool_name='Agent' AND i.deleted=0 AND r.deleted=0 AND b.deleted=0 AND b.status='failed'
            AND b.error_msg='interrupted by process restart'
            AND JSON_UNQUOTE(JSON_EXTRACT(IF(JSON_VALID(i.llm_oberserve),i.llm_oberserve,'{}'),'$.status'))='running' ''')).rowcount
        for table in ('ai_agent_user_question','ai_agent_plan_approval'):
            counts[table]=c.execute(text(f"""UPDATE {table} h LEFT JOIN ai_agent_dialogue_run r ON r.request_id=h.resume_request_id AND r.deleted=0
                SET h.status=CASE WHEN r.status IN (1,5) THEN 'ANSWERED' ELSE 'FAILED' END
                WHERE h.status='RESUMING' AND h.deleted=0""")).rowcount
        # Session status is a projection of its latest run; no successful/stopped run is rewritten.
        c.execute(text('''UPDATE ai_agent_dialogue_session s JOIN ai_agent_dialogue_run r ON r.request_id=s.latest_request_id
            SET s.status=r.status WHERE s.status=0 AND r.status<>0 AND s.deleted=0 AND r.deleted=0'''))
        c.execute(text('''UPDATE ai_agent_dialogue_session s JOIN ai_agent_dialogue_run r ON r.request_id=s.latest_request_id
            SET s.failed_run_count=(SELECT COUNT(*) FROM ai_agent_dialogue_run x WHERE x.session_id=s.session_id AND x.status IN (2,3,4) AND x.deleted=0)
            WHERE r.error_code='PROCESS_RESTART' AND r.deleted=0 AND s.deleted=0'''))
        return counts
    return await ledger.transact(work)
