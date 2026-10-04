"""Compare protocol objects without discarding fields, IDs, or list order.

Future Python captures use the same artifact shape. Normalize only explicit JSON
pointers supplied by each case; repeated IDs retain equality across references.
"""
import argparse
import copy
import json
from pathlib import Path


def normalize(document, pointers=()):
    result = copy.deepcopy(document)
    aliases = {}
    for pointer in pointers:
        parts = [s.replace('~1', '/').replace('~0', '~') for s in pointer.lstrip('/').split('/')]
        node = result
        for part in parts[:-1]:
            node = node[int(part)] if isinstance(node, list) else node[part]
        key = int(parts[-1]) if isinstance(node, list) else parts[-1]
        value = node[key]
        # Type remains part of identity: BIGINT/string and null must not collapse.
        if value is not None:
            token = (type(value).__name__, json.dumps(value, sort_keys=True))
            node[key] = {'dynamic': aliases.setdefault(token, f'<dynamic:{len(aliases)+1}>'), 'type': type(value).__name__}
    return result


def compare(expected, actual, path='$'):
    if type(expected) is not type(actual):
        return [f'{path}: type {type(expected).__name__} != {type(actual).__name__}']
    if isinstance(expected, dict):
        differences = [f'{path}: keys {sorted(expected)} != {sorted(actual)}'] if expected.keys() != actual.keys() else []
        for key in sorted(expected.keys() & actual.keys()):
            differences += compare(expected[key], actual[key], f'{path}.{key}')
        return differences
    if isinstance(expected, list):
        differences = [f'{path}: length {len(expected)} != {len(actual)}'] if len(expected) != len(actual) else []
        for i, (left, right) in enumerate(zip(expected, actual)):
            differences += compare(left, right, f'{path}[{i}]')
        return differences
    return [] if expected == actual else [f'{path}: {expected!r} != {actual!r}']


def assert_partial_order(events, edges):
    """Compare required event precedence without imposing a parallel-tool total order."""
    positions = {key: [i for i, e in enumerate(events) if e['key'] == key] for edge in edges for key in edge}
    for first, second in edges:
        if not positions[first] or not positions[second] or max(positions[first]) >= min(positions[second]):
            raise AssertionError(f'Missing/reversed precedence: {first} -> {second}')



def protocol_view(capture):
    """Retain raw golden files; compare JSON key order semantically, SSE framing literally.

    Dynamic history fields are projector task IDs at these two explicit
    paths. Equality between tool and summary IDs remains mandatory. The generated
    HITL resume ID is likewise normalized only at two declared answer pointers.
    """
    result=copy.deepcopy(capture)
    for group in ('http','history'):
        for case,response in result.get(group,{}).items():
            media=response.get('contentType') or ''
            if 'application/json' in media:
                body=json.loads(response['body'])
                if group=='history' and case=='detail' and body.get('data',{}).get('sessionId')=='session-history-p0':
                    body=normalize(body,[f'/data/runs/0/replayFrames/{i}/resultMap/eventData/taskId' for i in (0,1)])
                response['body']={'json':body}
            elif 'text/event-stream' in media and response['body'].startswith('data:'):
                response['body']={'lines':[{'data':json.loads(line[5:])} if line.startswith('data:') else {'literal':line}
                                          for line in response['body'].split('\n')]}
    if 'expired-answer-repeat' in result.get('hitl',{}):
        result=normalize(result,['/hitl/expired-answer-accepted/resumeRequestId','/hitl/expired-answer-repeat/resumeRequestId'])
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('expected', type=Path); p.add_argument('actual', type=Path)
    p.add_argument('--java-capture', action='store_true', help='Parse HTTP JSON/SSE and normalize only declared projector task IDs')
    p.add_argument('--dynamic-pointers', type=Path, help='JSON array of exact dynamic-field pointers in protocol_view, preserving reference equality')
    a = p.parse_args(); left=json.loads(a.expected.read_text()); right=json.loads(a.actual.read_text())
    if a.java_capture:left=protocol_view(left);right=protocol_view(right)
    if a.dynamic_pointers:
        pointers=json.loads(a.dynamic_pointers.read_text());left=normalize(left,pointers);right=normalize(right,pointers)
    failures=compare(left,right)
    if failures: raise SystemExit('\n'.join(failures))
    print('PASS')
