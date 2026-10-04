"""Anchor protected file delivery to an allowed session directory and a regular FD."""
import os
import stat
from pathlib import Path
from fastapi.responses import FileResponse


def open_session_file(path,session):
    from reactor_tool.docgen.paths import OUTPUT_DIR,UPLOAD_DIR
    bases=[Path(os.getenv('FILE_SAVE_PATH','file_db_dir')),OUTPUT_DIR,UPLOAD_DIR]
    if os.getenv('REACTOR_WORKSPACE_ROOT'):bases.append(Path(os.environ['REACTOR_WORKSPACE_ROOT']))
    if not session or '/' in session or '\\' in session or session in ('.','..'):raise PermissionError('Invalid file scope')
    target=Path(os.path.abspath(path))
    for base in bases:
        lexical=Path(os.path.abspath(base));base=lexical.resolve()
        try:parts=target.relative_to(lexical/session).parts
        except ValueError:
            try:parts=target.relative_to(base/session).parts
            except ValueError:continue
        if not parts or '..' in parts:continue
        fd=os.open(base,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            for part in (session,*parts[:-1]):
                child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=child
            result=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
            if not stat.S_ISREG(os.fstat(result).st_mode):os.close(result);raise PermissionError('Regular file required')
            return result
        finally:os.close(fd)
    raise PermissionError('File must remain inside its registered session')


class AnchoredFileResponse(FileResponse):
    """Reuse Starlette's Range/HEAD/headers while holding an immutable file identity."""
    def __init__(self,fd,**kwargs):
        self.fd=fd
        super().__init__(f'/dev/fd/{fd}',stat_result=os.fstat(fd),**kwargs)
    async def __call__(self,scope,receive,send):
        try:await super().__call__(scope,receive,send)
        finally:os.close(self.fd)
