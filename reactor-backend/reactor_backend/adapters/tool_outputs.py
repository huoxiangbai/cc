"""Write existing Java typed tool tables atomically with invocation completion."""
from sqlalchemy import text
from reactor_backend.models.tool_outputs import OUTPUT_TABLES
from reactor_backend.adapters.mysql import rows

FIELDS={'deep_search':('query','answer_summary','stages_json'),
        'code_interpreter':('code_output','content','code','explain'),
        'data_analysis':('task','summary','content'),
        'multimodalagent_tool':('summary','markdown_content'),
        'emit_ui_tree':('canvas_id','salvaged','tree_json'),
        'emit_ui_patch':('canvas_id','seq','patches_json'),
        'canvas_publish':('title','mode','primary_file_name','preview_url','download_url','open_in_panel','salvaged'),
        'image_generation_tool':('prompt','mode','summary','size','batch_count','source_image_count','mask_image_count','used_fallback')}


def save(c,id,reply,status):
    tools=rows(c,'SELECT t.*,r.request_id,r.session_id FROM ai_agent_tool_invocation t JOIN ai_agent_dialogue_run r ON r.id=t.run_id WHERE t.id=:id',id=id)
    if not tools or tools[0]['tool_name'] not in FIELDS:return
    t=tools[0];name=t['tool_name'];payload=reply.structured_output or {}
    values={key:payload.get(key) for key in FIELDS[name]}
    values.update(tool_invocation_id=id,run_id=t['run_id'],request_id=t['request_id'],session_id=t['session_id'],
                  tool_call_id=t['tool_call_id'],status=status,error_msg=reply.error)
    if name=='image_generation_tool':values['request_source']='agent'
    columns=','.join('`'+k+'`' for k in values);args=','.join(':'+k for k in values)
    table='ai_agent_tool_output_'+OUTPUT_TABLES[name]
    c.execute(text(f'INSERT INTO {table} ({columns}) VALUES ({args}) ON DUPLICATE KEY UPDATE '+','.join('`'+k+'`=VALUES(`'+k+'`)' for k in values)),values)
