"""Scoped workspace IO using anchored directory descriptors, never shared Skill writes."""
import fnmatch
import hashlib
import os
from pathlib import PurePosixPath
import re
import stat
from contextlib import contextmanager


class Workspace:
    def __init__(self, root, session, read_state=None, allow_skills=False):
        self.root=root
        self.session=session
        self.allow_skills=allow_skills
        self.read_state={} if read_state is None else read_state
        if not session or '/' in session or '\\' in session or session in ('.','..'):
            raise ValueError('Invalid session workspace')

    def parts(self,path,allow_skills=False):
        p=str(path or '.').replace('\\','/')
        if p.startswith('/') or '..' in p.split('/') or '\x00' in p or ':' in p:
            raise ValueError('Path must remain inside the session workspace')
        parts=[v for v in p.split('/') if v and v!='.']
        if parts and parts[0]=='skills' and not (allow_skills or self.allow_skills):
            raise ValueError('Shared Skill access requires the scoped Skill runtime')
        return parts

    @contextmanager
    def directory(self,parts,create=False):
        self.root.mkdir(parents=True,exist_ok=True)
        fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            for part in [self.session]+parts:
                if create:
                    try:os.mkdir(part,dir_fd=fd)
                    except FileExistsError:pass
                next_fd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                os.close(fd);fd=next_fd
            yield fd
        finally:os.close(fd)

    @contextmanager
    def opened(self,path,flags,create=False):
        parts=self.parts(path)
        if not parts:raise ValueError('File path is required')
        with self.directory(parts[:-1],create) as directory:
            fd=os.open(parts[-1],flags|os.O_NOFOLLOW,0o600,dir_fd=directory)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):raise ValueError('Regular file required')
                yield fd
            finally:os.close(fd)

    def read(self,path):
        return self.read_bytes(path).decode('utf-8')

    def read_bytes(self,path):
        with self.opened(path,os.O_RDONLY) as fd:
            size=os.fstat(fd).st_size
            if size>8*1024*1024:raise ValueError('File exceeds workspace read budget')
            data=b''
            while chunk:=os.read(fd,65536):data+=chunk
        return data

    def write(self,path,content):
        if not isinstance(content,str):raise ValueError('content is required')
        if len(content)>1000000:raise ValueError('content exceeds workspace write budget')
        self.write_bytes(path,content.encode('utf-8'))
        self.read_state[str(path)]=(hashlib.sha256(content.encode()).hexdigest(),1,2147483647)
        return content

    def write_bytes(self,path,data):
        if len(data)>32*1024*1024:raise ValueError('File exceeds write budget')
        with self.opened(path,os.O_WRONLY|os.O_CREAT,True) as fd:
            os.ftruncate(fd,0)
            while data:
                count=os.write(fd,data);data=data[count:]
            os.fsync(fd)

    def walk(self,path='.',depth=64):
        parts=self.parts(path)
        entries=[]
        with self.directory(parts,True) as fd:
            def visit(directory,prefix,remaining):
                for name in sorted(os.listdir(directory)):
                    info=os.stat(name,dir_fd=directory,follow_symlinks=False)
                    relative=prefix+name
                    if stat.S_ISLNK(info.st_mode):continue
                    is_dir=stat.S_ISDIR(info.st_mode)
                    entries.append(dict(type='DIR' if is_dir else 'FILE',path=relative,**({} if is_dir else {'bytes':info.st_size})))
                    if len(entries)>2000:return
                    if is_dir and remaining>1:
                        child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
                        try:visit(child,relative+'/',remaining-1)
                        finally:os.close(child)
            visit(fd,'',depth)
        return entries

    def execute(self,name,a):
        path=str(a.get('path') or '.')
        if name=='workspace_write':
            content=self.write(path,a.get('content'))
            return dict(path=path,chars=len(content))
        if name=='workspace_edit':
            content=self.read(path);previous=self.read_state.get(path)
            if not previous:raise ValueError('You must use workspace_read before editing')
            if previous[0]!=hashlib.sha256(content.encode()).hexdigest():raise ValueError('File has been modified since read. Read it again with workspace_read.')
            old=a.get('old_string');new=a.get('new_string')
            if not isinstance(old,str) or not old or not isinstance(new,str) or old==new:raise ValueError('Invalid old_string/new_string')
            count=content.count(old)
            if count==0 or count>1 and not a.get('replace_all'):raise ValueError('old_string must match; ambiguous matches require replace_all')
            updated=content.replace(old,new) if a.get('replace_all') else content.replace(old,new,1)
            self.write(path,updated)
            return dict(path=path,replacements=count if a.get('replace_all') else 1,charsBefore=len(content),charsAfter=len(updated))
        if name=='workspace_read':
            content=self.read(path);lines=content.splitlines()
            start=max(1,int(a.get('start_line',a.get('offset',1))));count=max(1,int(a.get('line_count',a.get('limit',2000))))
            state=(hashlib.sha256(content.encode()).hexdigest(),start,count)
            if self.read_state.get(path)==state:
                return dict(type='file_unchanged',unchanged=True,path=path,startLine=start,lineCount=count,message='File unchanged since last read. The content from the earlier workspace_read tool_result in this conversation is still current — refer to that instead of re-reading.')
            self.read_state[path]=state
            selected=lines[start-1:start-1+count];body=''.join(f'{i} | {line}\n' for i,line in enumerate(selected,start))
            return dict(type='text',path=path,startLine=start,endLine=min(len(lines),start-1+count),numLines=len(selected),totalLines=len(lines),content=body[:96000],**({'truncated':True} if len(body)>96000 else {}))
        if name=='workspace_list':return dict(path=path,entries=self.walk(path,max(1,int(a.get('max_depth',2)))))
        if name=='workspace_glob':
            pattern=str(a.get('pattern') or '')
            if not pattern:raise ValueError('pattern is required')
            return dict(path=path,pattern=pattern,files=[e['path'] for e in self.walk(path) if e['type']=='FILE' and (fnmatch.fnmatchcase(e['path'],pattern) or pattern.startswith('**/') and fnmatch.fnmatchcase(e['path'],pattern[3:]))])
        if name=='workspace_grep':
            pattern=str(a.get('pattern') or '')
            if not pattern:raise ValueError('pattern is required')
            regex=re.compile(pattern if a.get('regex') else re.escape(pattern),0 if a.get('case_sensitive') else re.I)
            try:entries=self.walk(path)
            except NotADirectoryError:entries=[dict(type='FILE',path=PurePosixPath(path).name)];path=str(PurePosixPath(path).parent)
            matches=[]
            for entry in entries:
                if entry['type']!='FILE':continue
                try:content=self.read(str(PurePosixPath(path)/entry['path']))
                except UnicodeDecodeError:continue
                for line_no,line in enumerate(content.splitlines(),1):
                    if regex.search(line):matches.append(dict(path=entry['path'],line=line_no,content=line[:2000]))
                    if len(matches)>=500:return dict(path=path,pattern=pattern,matches=matches,truncated=True)
            return dict(path=path,pattern=pattern,matches=matches)
        raise ValueError('Unknown workspace operation')
