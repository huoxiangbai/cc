import io
import json
import re
import stat
import zipfile
from pathlib import Path,PurePosixPath
from reactor_backend.runtime.workspace import Workspace


def name(value):
    value=str(value or '').strip()
    if not re.fullmatch(r'[\w][\w.-]{0,127}',value):raise ValueError('Invalid Skill name')
    return value


def segment(value):
    return re.sub(r'[^A-Za-z0-9._-]+','-',value.strip())[:80].strip('.-') or 'skill'


def parse(text,fallback=None):
    fields={};body=text
    if text.startswith('---'):
        match=re.match(r'^---\s*\n(.*?)\n---\s*\n?',text,re.S)
        if not match:raise ValueError('Invalid Skill frontmatter')
        import yaml
        fields=yaml.safe_load(match[1]) or {};body=text[match.end():]
        if not isinstance(fields,dict):raise ValueError('Skill frontmatter must be a mapping')
    resolved=name(fields.get('name') or fallback)
    if not body.strip():raise ValueError('Empty Skill manual')
    return dict(name=resolved,description=str(fields.get('description') or ''),content=body.strip())


class Registry:
    def __init__(self,root):
        self.root=Path(root) if root else None;self.definitions={};self.errors={}
        if root:self.reload()

    def io(self):
        if not self.root:raise ValueError('Explicit Skill root is required')
        return Workspace(self.root.parent,self.root.name,allow_skills=True)

    def reload(self):
        loaded={};errors={}
        if not self.root:return
        guard=self.io()
        for entry in guard.walk('.',1):
            if entry['type']!='DIR':continue
            directory=entry['path']
            try:
                manual=parse(guard.read(directory+'/SKILL.md'),directory)
                if manual['name'] in loaded:raise ValueError('Duplicate Skill name')
                manual['_directory']=directory
                manual['_segment']=segment(manual['name'])
                manual['availableScripts']=[e['path'] for e in guard.walk(directory) if e['type']=='FILE' and e['path'].startswith('scripts/') and Path(e['path']).suffix.lower() in ('.py','.sh','.js','.mjs','.ps1')]
                loaded[manual['name']]=manual
            except (ValueError,OSError) as exc:errors[directory]=str(exc)
        self.definitions,self.errors=loaded,errors

    def list(self):
        return [dict(name=n,description=d['description'],scriptCount=len(d['availableScripts']),source='system',location='skills/'+d['_segment']) for n,d in sorted(self.definitions.items())]

    def resolve(self,n):
        n=name(n)
        found=[d for key,d in self.definitions.items() if n.lower() in {key.lower(),d['_directory'].lower(),d['_segment'].lower()}]
        if len(found)>1:raise ValueError('Ambiguous Skill path alias')
        return found[0] if found else None

    def manual(self,n,disabled=()):
        n=name(n)
        resolved=self.resolve(n)
        if resolved and {n.lower(),resolved['name'].lower(),resolved['_directory'].lower(),resolved['_segment'].lower()} & {v.lower() for v in disabled}:raise PermissionError('Skill disabled for this session')
        if n.lower() in {v.lower() for v in disabled}:raise PermissionError('Skill disabled for this session')
        d=resolved
        if not d:raise ValueError(self.errors.get(n,'Unknown Skill: '+n))
        n=d['name'];virtual=d['_segment']
        content=d['content'].replace('${SKILL_DIR}','skills/'+virtual).replace('${PYTHON}','python')
        return dict(tool='skill_tool',ok=True,name=n,description=d['description'],content=content,skillDir='skills/'+virtual,availableScripts=['- '+rel+' | run: '+('node' if rel.endswith(('.js','.mjs')) else 'bash' if rel.endswith('.sh') else 'powershell -File' if rel.endswith('.ps1') else 'python')+' skills/'+virtual+'/'+rel for rel in d['availableScripts']])

    def package(self,data):
        if len(data)>32*1024*1024:raise ValueError('Skill package exceeds budget')
        files={};total=0
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for entry in z.infolist():
                p=PurePosixPath(entry.filename.replace('\\','/'))
                if p.is_absolute() or '..' in p.parts or ':' in str(p) or stat.S_ISLNK(entry.external_attr>>16):raise ValueError('Unsafe package path')
                if entry.is_dir():continue
                total+=entry.file_size
                if len(files)>=2000 or total>32*1024*1024:raise ValueError('Skill package expands beyond budget')
                if str(p) in files:raise ValueError('Duplicate package entry')
                files[str(p)]=z.read(entry)
        manuals=[p for p in files if p=='SKILL.md' or p.endswith('/SKILL.md')]
        if len(manuals)!=1:raise ValueError('Package must contain one SKILL.md')
        prefix=manuals[0][:-len('SKILL.md')]
        if any(not p.startswith(prefix) for p in files):raise ValueError('Files outside package root')
        d=parse(files[manuals[0]].decode('utf-8'),PurePosixPath(prefix.rstrip('/')).name if prefix else None)
        return d,{p[len(prefix):]:data for p,data in files.items()}

    def preview(self,data):
        d,files=self.package(data)
        return dict(name=d['name'],description=d['description'],contentPreview=d['content'][:800],extraFiles=[p for p in files if p!='SKILL.md'],nameTaken=d['name'] in self.definitions)

    def install(self,data,replace=False):
        d,files=self.package(data);n=d['name'];guard=self.io()
        if n in self.definitions and not replace:raise ValueError('Skill exists; use replace=true')
        if replace:self.delete(n)
        for relative,data in files.items():guard.write_bytes(n+'/'+relative,data)
        self.reload();return next(r for r in self.list() if r['name']==n)

    def create(self,args):
        raw=args.get('content') or '';d=parse(raw,args.get('name'))
        n=name(args.get('name') or d['name']);description=args.get('description') or d['description']
        if n in self.definitions and not args.get('replace'):raise ValueError('Skill exists; use replace=true')
        text='---\nname: '+json.dumps(n)+'\ndescription: '+json.dumps(description,ensure_ascii=False)+'\n---\n'+d['content']+'\n'
        self.io().write(n+'/SKILL.md',text);self.reload();return next(r for r in self.list() if r['name']==n)

    def delete(self,n):
        import os
        n=name(n);guard=self.io()
        resolved=self.resolve(n)
        if resolved:n=resolved['_directory']
        try:
            with guard.directory([n]) as fd:
                def remove(directory):
                    for item in os.listdir(directory):
                        info=os.stat(item,dir_fd=directory,follow_symlinks=False)
                        if stat.S_ISLNK(info.st_mode):raise ValueError('Symlink in Skill package')
                        if stat.S_ISDIR(info.st_mode):
                            child=os.open(item,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
                            try:remove(child)
                            finally:os.close(child)
                            os.rmdir(item,dir_fd=directory)
                        else:os.unlink(item,dir_fd=directory)
                remove(fd)
            with guard.directory([]) as fd:os.rmdir(n,dir_fd=fd)
        except FileNotFoundError:return False
        self.reload();return True

    async def import_url(self,client,url,replace=False):
        from urllib.parse import urlparse
        if urlparse(url).scheme not in ('http','https'):raise ValueError('URL must be HTTP(S)')
        data=b''
        async with client.stream('GET',url,follow_redirects=True) as r:
            r.raise_for_status()
            async for chunk in r.aiter_bytes():
                data+=chunk
                if len(data)>32*1024*1024:raise ValueError('Downloaded Skill exceeds budget')
        return self.install(data,replace) if data.startswith(b'PK') else self.create(dict(content=data.decode('utf-8'),replace=replace))


class SkillScope:
    """Session copies keep scripts and authoring workflows usable without global writes."""
    def __init__(self,registry,workspace,disabled):
        self.registry=registry;self.workspace=workspace;self.disabled=set(disabled)
        # Anchored creation verifies the full session chain before constructing its IO root.
        with workspace.directory(['.reactor'],True):pass
        self.local=Workspace(workspace.root/workspace.session/'.reactor','skill-library',allow_skills=True)
        self.materialized=set()

    def manual(self,n):
        n=name(n)
        resolved=self.registry.resolve(n)
        aliases={n.lower()} | ({resolved['name'].lower(),resolved['_directory'].lower(),resolved['_segment'].lower()} if resolved else set())
        if aliases & {v.lower() for v in self.disabled}:raise PermissionError('Skill disabled for this session')
        for entry in self.local.walk('.',1):
            if entry['type']!='DIR':continue
            try:
                d=parse(self.local.read(entry['path']+'/SKILL.md'),entry['path'])
                if d['name']==n or resolved and d['name']==resolved['name']:
                    n=entry['path'];break
            except FileNotFoundError:continue
        try:
            content=self.local.read(n+'/SKILL.md')
            definition=parse(content,n)
            scripts=[e['path'] for e in self.local.walk(n) if e['type']=='FILE' and e['path'].startswith('scripts/')]
            return dict(tool='skill_tool',ok=True,name=definition['name'],description=definition['description'],content=definition['content'].replace('${SKILL_DIR}','skills/'+n).replace('${PYTHON}','python'),skillDir='skills/'+n,availableScripts=scripts)
        except FileNotFoundError:return self.registry.manual(n,self.disabled)

    def list(self):
        entries={d['name']:d for d in self.registry.list() if d['name'].lower() not in {n.lower() for n in self.disabled}}
        for entry in self.local.walk('.',1):
            if entry['type']=='DIR' and entry['path'].lower() not in {n.lower() for n in self.disabled}:
                try:
                    d=parse(self.local.read(entry['path']+'/SKILL.md'),entry['path'])
                    if d['name'].lower() not in {v.lower() for v in self.disabled}:entries[d['name']]=dict(name=d['name'],description=d['description'],source='session')
                except FileNotFoundError:continue
        return list(entries.values())

    def materialize(self,n):
        n=name(n)
        resolved=self.registry.resolve(n)
        aliases={n.lower()} | ({resolved['name'].lower(),resolved['_directory'].lower(),resolved['_segment'].lower()} if resolved else set())
        if aliases & {v.lower() for v in self.disabled}:raise PermissionError('Skill disabled for this session')
        if n in self.materialized:return
        # Preserve an existing edited session copy across turns.
        try:self.local.read(n+'/SKILL.md')
        except FileNotFoundError:
            if not resolved:raise ValueError('Unknown Skill: '+n)
            source=self.registry.io()
            for entry in source.walk(resolved['_directory']):
                if entry['type']=='FILE':self.local.write_bytes(n+'/'+entry['path'],source.read_bytes(resolved['_directory']+'/'+entry['path']))
        self.materialized.add(n)

    def execute(self,operation,args):
        path=str(args.get('path') or '.')
        if path.replace('\\','/').startswith('skills/'):
            parts=self.workspace.parts(path,allow_skills=True)
            if len(parts)>1:
                n=name(parts[1])
                if self.registry.resolve(n):self.materialize(n)
                elif n.lower() in {v.lower() for v in self.disabled}:raise PermissionError('Skill disabled')
            args={**args,'path':'/'.join(parts[1:]) or '.'}
            result=self.local.execute(operation,args)
            if 'path' in result:result['path']='skills/'+result['path']
            return result
        return self.workspace.execute(operation,args)

    def disabled_aliases(self):
        aliases=set(self.disabled)
        for ref in self.disabled:
            d=self.registry.resolve(ref)
            if d:aliases.update((d['name'],d['_directory'],d['_segment']))
        for entry in self.local.walk('.',1):
            if entry['type']=='DIR':
                try:
                    d=parse(self.local.read(entry['path']+'/SKILL.md'),entry['path'])
                    if d['name'].lower() in {v.lower() for v in self.disabled}:aliases.add(entry['path'])
                except FileNotFoundError:continue
        return aliases

    def bash_library(self,command):
        for n in re.findall(r'(?:^|[^\w.-])(?:\./)?skills[/\\]+([\w.-]+)',command):
            self.materialize(n)
        return str(self.local.root/self.local.session)
