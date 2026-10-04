"""Read-side GenUI normalization, matching original GenUiSchema; no new tools."""
import json
from uuid import uuid4
from pathlib import Path

KINDS = frozenset(json.loads(Path(__file__).with_name('genui_kinds.json').read_text()))


def decode(value, default=None):
    if not isinstance(value, str):
        return value if value is not None else default
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def string(value):
    if value is None:
        return None
    return str(value).strip() or None


def tree(raw):
    if not isinstance(raw, dict):
        raise ValueError('tree must be an object')
    if isinstance(raw.get('tree'), dict) and set(raw) <= {'tree', 'canvas_id'}:
        return tree(raw['tree'])
    if 'root' in raw or 'schemaVersion' in raw:
        root = raw.get('root')
        if not isinstance(root,dict):raise ValueError('envelope requires root object')
    elif 'kind' in raw or 'type' in raw:
        root = raw
    else:
        raise ValueError('invalid tree envelope; expected {schemaVersion,root} or bare root')
    count = 0
    def node(value, depth):
        nonlocal count
        if not isinstance(value, dict):
            raise ValueError('children must be node objects, not primitives')
        count += 1
        if count > 200 or depth > 24:
            raise ValueError(f'tree depth {depth} exceeds max 24' if depth>24 else f'tree node count {count} exceeds max 200')
        kind = string(value.get('kind')) or string(value.get('type'))
        if not kind:raise ValueError('node.kind is required')
        if kind not in KINDS:
            raise ValueError('unsupported kind: '+kind+'; call list_ui_components')
        props = dict(value['props']) if isinstance(value.get('props'), dict) else {}
        for key, val in value.items():
            if key not in {'nodeId','kind','props','children','type'}:
                props.setdefault(key, val)
        for source, target in [('text','value'),('title','value'),('content','value'),('label','value'),('url','src'),('imageUrl','src'),('href','url')]:
            if source in props:
                props.setdefault(target, props[source])
        children = value.get('children') if isinstance(value.get('children'), list) else []
        return dict(nodeId=string(value.get('nodeId')) or 'n_'+uuid4().hex[:12],kind=kind,props=props,
                    children=[node(child,depth+1) for child in children if child is not None])
    return {'schemaVersion':'1','root':node(root,1)}


def patch(raw):
    if not isinstance(raw,dict):raise ValueError('patch payload must be an object')
    if not isinstance(raw.get('patches'),list) or not raw['patches']:raise ValueError('patches must be a non-empty array')
    if len(raw['patches'])>200:raise ValueError('patches exceeds max 200')
    result=[]
    for p in raw['patches']:
        if not isinstance(p,dict):
            raise ValueError('each patch must be an object')
        op,path=string(p.get('op')),string(p.get('path'))
        if op not in ('add','replace','remove'):raise ValueError('patch.op must be add|replace|remove')
        if not path or not path.startswith('/'):raise ValueError('patch.path must be an RFC6901 pointer starting with /')
        item=dict(op=op,path=path)
        if op!='remove':
            if 'value' not in p: raise ValueError('patch.value required for op='+op)
            item['value']=p['value']
        result.append(item)
    value={'patches':result}
    if raw.get('canvas_id') is not None: value['canvas_id']=str(raw['canvas_id'])
    if raw.get('seq') is not None: value['seq']=raw['seq']
    return value


def recover(invocation, params):
    name = invocation['tool_name']
    output = invocation.get('structured_output') or {}
    value = {'isFinal':True,'toolCallId':invocation['tool_call_id'],'toolName':name}
    if name == 'emit_ui_tree':
        recovered = decode(output.get('tree_json'))
        if recovered is None:
            try: recovered = tree(params.get('tree',params))
            except (ValueError,TypeError,RecursionError): recovered = None
        if recovered is not None: value['tree']=recovered
        canvas=output.get('canvas_id')
        if canvas and canvas.strip(): value['canvas_id']=canvas
        return 'ui_tree',value
    if name == 'emit_ui_patch':
        recovered=decode(output.get('patches_json'))
        canvas,seq=output.get('canvas_id'),output.get('seq')
        if not recovered:
            try:
                normalized=patch(params);recovered=normalized['patches']
                if canvas is None: canvas=normalized.get('canvas_id')
                if seq is None and isinstance(normalized.get('seq'),(int,float)) and not isinstance(normalized['seq'],bool): seq=int(normalized['seq'])
            except (ValueError,TypeError): recovered=None
        if recovered is not None: value['patches']=recovered
        if canvas and canvas.strip(): value['canvas_id']=canvas
        if seq is not None: value['seq']=seq
        return 'ui_patch',value
    return None
