"""Approved original Tool guard wiring, with ONLY new temporary files."""
import builtins
import io
import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'reactor-tool'))
from reactor_tool.tool.code_interpreter_policy import build_permission_policy,CodeExecutionPermissionError
from reactor_tool.tool.code_interpreter_runtime_guard import activate_runtime_io_guard
from reactor_tool.tool.python_sandbox_executor import _sandbox_environment

@pytest.mark.parametrize('op',['builtins','io','pathlib'])
def test_existing_runtime_validator_rejects_dynamic_outside_path(tmp_path,monkeypatch,op):
    for key in ('PRE_EXECUTION_VALIDATION','PATH_SANDBOX','RUNTIME_DOUBLE_CHECK'):
        monkeypatch.setenv('CODE_INTERPRETER_ENABLE_'+key,'true')
    root=tmp_path/'workspace';root.mkdir();external=tmp_path/'outside.txt';external.write_text('test only')
    policy=build_permission_policy(profile='workspace',workspace_root=str(root),output_dir=str(root/'output'),input_files=[])
    # Rebind patched functions after activation, so the test calls the actual guarded surface.
    with activate_runtime_io_guard(policy):
        operation={'builtins':builtins.open,'io':io.open,'pathlib':lambda p:Path(p).open()}[op]
        with pytest.raises(CodeExecutionPermissionError):operation(str(external)).read()
        with builtins.open('allowed.txt','w') as f:f.write('actual permitted write')
    assert (root/'allowed.txt').read_text()=='actual permitted write'


def test_only_approved_guard_flags_enter_original_subprocess(monkeypatch):
    keys=['CODE_INTERPRETER_ENABLE_'+s for s in ('PRE_EXECUTION_VALIDATION','PATH_SANDBOX','RUNTIME_DOUBLE_CHECK')]
    for k in keys:monkeypatch.setenv(k,'true')
    monkeypatch.setenv('OPENAI_API_KEY','test-secret-must-not-propagate')
    env=_sandbox_environment()
    assert all(env[k]=='true' for k in keys) and 'OPENAI_API_KEY' not in env
