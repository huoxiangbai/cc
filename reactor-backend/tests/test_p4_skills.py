import io
import json
from pathlib import Path
import stat
import zipfile
import pytest
from reactor_backend.skills.registry import Registry,SkillScope
from reactor_backend.runtime.workspace import Workspace


def package(extra=None):
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as z:
        z.writestr('original/SKILL.md','---\nname: original\ndescription: "真实技能"\n---\n# Manual\npython skills/original/scripts/run.py\n')
        z.writestr('original/scripts/run.py','print("实际运行")\n')
        for n,v in (extra or {}).items():z.writestr(n,v)
    return buffer.getvalue()


def test_package_discovery_on_demand_reload_and_session_copy(tmp_path):
    registry=Registry(tmp_path/'library')
    registry.install(package())
    assert registry.list()[0]['scriptCount']==1
    assert registry.manual('original')['availableScripts']
    with pytest.raises(ValueError):registry.install(package())
    a=SkillScope(registry,Workspace(tmp_path/'work','a'),[])
    b=SkillScope(registry,Workspace(tmp_path/'work','b'),[])
    a.execute('workspace_write',{'path':'skills/original/scripts/run.py','content':'print("session A")'})
    assert '实际运行' in b.execute('workspace_read',{'path':'skills/original/scripts/run.py'})['content']
    assert '实际运行' in registry.io().read('original/scripts/run.py')
    registry.create(dict(name='original',content='# Revised manual',replace=True))
    assert registry.manual('original')['content']=='# Revised manual' and registry.io().read('original/scripts/run.py')
    assert registry.delete('original') and registry.list()==[]


@pytest.mark.parametrize('path',['../escape','/absolute','original/../../escape','C:/escape'])
def test_zip_slip_rejected(tmp_path,path):
    registry=Registry(tmp_path/'lib')
    with pytest.raises(ValueError):registry.install(package({path:'evil'}))


def test_symlinks_and_disabled_alias_cannot_bypass_scope(tmp_path):
    registry=Registry(tmp_path/'lib');registry.install(package())
    scope=SkillScope(registry,Workspace(tmp_path/'work','a'),['original'])
    for action,args in [('workspace_read',{'path':'skills/original/SKILL.md'}),('workspace_write',{'path':'skills/original/SKILL.md','content':'evil'})]:
        with pytest.raises(PermissionError):scope.execute(action,args)
    with pytest.raises(PermissionError):scope.bash_library('python skills/ORIGINAL/scripts/run.py')
    outside=tmp_path/'secret';outside.write_text('private')
    (tmp_path/'lib/original/scripts/symlink.py').symlink_to(outside)
    with pytest.raises(OSError):registry.io().read('original/scripts/symlink.py')
    with pytest.raises(ValueError):scope.execute('workspace_read',{'path':'skills/original/../../secret'})


def test_original_skill_creator_package_script_is_materialized(tmp_path):
    import shutil
    original=Path(__file__).resolve().parents[2]/'runtime/skills/skill-creator'
    # Copy only this original package to a new test root; never writes repository Skills.
    shutil.copytree(original,tmp_path/'lib/skill-creator',ignore=shutil.ignore_patterns('__pycache__','.DS_Store'))
    registry=Registry(tmp_path/'lib');assert 'skill-creator' in registry.definitions,registry.errors
    scope=SkillScope(registry,Workspace(tmp_path/'work','session'),[])
    library=Path(scope.bash_library('python skills/skill-creator/scripts/package_skill.py'))
    assert (library/'skill-creator/scripts/package_skill.py').read_bytes()==(original/'scripts/package_skill.py').read_bytes()


def test_all_original_skill_names_and_unicode_alias_discovery(tmp_path):
    import shutil
    original=Path(__file__).resolve().parents[2]/'runtime/skills'
    registry=Registry(original)
    assert len(registry.definitions)==len(list(original.glob('*/SKILL.md')))
    assert not registry.errors
    manual=registry.manual('学霸笔记');assert manual['skillDir']=='skills/skill' and manual['name']=='学霸笔记'
    scope=SkillScope(registry,Workspace(tmp_path/'work','session'),['学霸笔记'])
    for alias in ('scholar-notes','skill','学霸笔记'):
        with pytest.raises(PermissionError):scope.execute('workspace_read',{'path':'skills/'+alias+'/SKILL.md'})


async def test_real_bash_child_does_not_inherit_provider_or_service_keys(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]/"reactor-tool"))
    from reactor_tool.tool.bash_sandbox import _exec_local_shell
    monkeypatch.setenv('REACTOR_TOOL_SERVICE_TOKEN','test-only-private-token')
    monkeypatch.setenv('OPENAI_API_KEY','test-only-provider-key')
    code,out,err,_,timed=await _exec_local_shell('printf "%s|%s" "$REACTOR_TOOL_SERVICE_TOKEN" "$OPENAI_API_KEY"',tmp_path,5,1000)
    assert code==0 and out=='|' and not timed and not err

async def test_native_bash_confines_session_and_keeps_real_python_scripts(tmp_path,monkeypatch):
    import sys
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]/'reactor-tool'))
    from reactor_tool.tool.bash_sandbox import _exec_local_shell
    a=tmp_path/'a';a.mkdir();library=a/'.reactor/skill-library';library.mkdir(parents=True)
    shared=tmp_path/'shared';shared.mkdir();(shared/'SKILL.md').write_text('global unchanged')
    foreign=tmp_path/'b';foreign.mkdir();(foreign/'private.txt').write_text('other session')
    script=a/'run.py';script.write_text('from pathlib import Path\nimport yaml\nPath("result.txt").write_text(yaml.safe_dump({"real":True}))\n')
    command=str(Path(sys.executable))+' run.py'
    if sys.platform!='darwin':
        with pytest.raises(RuntimeError,match='native macOS'):
            await _exec_local_shell(command,a,10,10000,library)
        return
    code,out,err,_,timed=await _exec_local_shell(command,a,10,10000,library)
    assert code==0 and not timed,(out,err)
    assert 'true' in (a/'result.txt').read_text()
    for command in ('cat '+str(foreign/'private.txt'),'cat /etc/passwd','echo evil > '+str(shared/'SKILL.md')):
        code,out,err,_,_=await _exec_local_shell(command,a,10,10000,library)
        assert code!=0 and 'Operation not permitted' in err,(code,out,err)
    assert (shared/'SKILL.md').read_text()=='global unchanged'
    import shutil
    shutil.rmtree(a/'.reactor/bash-scope')
    (a/'.reactor/bash-scope').symlink_to(foreign,target_is_directory=True)
    with pytest.raises(OSError):await _exec_local_shell('echo no',a,10,1000,library)
    assert not (foreign/'home').exists()
