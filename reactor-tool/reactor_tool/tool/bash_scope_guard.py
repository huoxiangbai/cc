"""Kernel-enforced local Bash scope for the approved Python session-copy policy.

Legacy Java calls are unchanged. New session-copy calls fail closed if local
native confinement is unavailable; E2B keeps its existing remote isolation.
"""
import json
import os
from pathlib import Path
import shutil
import sys


def confined_argv(argv, workspace, library, environment):
    workspace=Path(workspace).resolve();library=Path(library).resolve()
    expected=workspace/'.reactor/skill-library'
    if library!=expected:raise PermissionError('Skill library must be the owning session copy')
    if sys.platform!='darwin' or not Path('/usr/bin/sandbox-exec').is_file():
        raise RuntimeError('Local session-copy Bash requires native macOS confinement; configure the existing E2B backend on other platforms')
    # Anchor every created component; an earlier script cannot redirect the host
    # through a symlink before the next sandbox is entered.
    fd=os.open(workspace,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for component in ('.reactor','bash-scope'):
            try:os.mkdir(component,mode=0o700,dir_fd=fd)
            except FileExistsError:pass
            child=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=child
        for child,key in (('home','HOME'),('tmp','TMPDIR')):
            try:os.mkdir(child,mode=0o700,dir_fd=fd)
            except FileExistsError:pass
            checked=os.open(child,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(checked)
            environment[key]=str(workspace/'.reactor/bash-scope'/child)
    finally:os.close(fd)
    # Read interpreter distributions and installed packages, never repository roots.
    roots={Path(sys.base_prefix).resolve(),Path(sys.prefix).resolve()}
    for binary in ('bash','sh','python','python3','node'):
        found=shutil.which(binary,path=environment.get('PATH'))
        if found:roots.add(Path(found).resolve().parent)
    for value in json.loads(os.environ.get('BASH_SANDBOX_READ_ROOTS','[]')):
        path=Path(value)
        if not path.is_absolute():raise ValueError('Bash runtime read roots must be absolute')
        roots.add(path.resolve())
    literal=lambda p:json.dumps(str(p))
    read=' '.join('(subpath '+literal(p)+')' for p in sorted(roots,key=str))
    policy='''(version 1)
(deny default)
(allow process* sysctl-read mach-lookup network*)
(allow file-read-metadata)
(allow file-read* (subpath "/System") (subpath "/usr/lib") (subpath "/usr/share") (subpath "/private/var/db/dyld") (subpath "/usr/bin") (subpath "/bin") (subpath "/sbin") (subpath "/dev") (subpath "/opt/homebrew/Cellar") (subpath "/opt/homebrew/lib") (subpath "/Library/Apple") (literal "/") (literal "/private") (literal "/private/etc") (literal "/etc") (literal "/private/etc/localtime") (literal "/private/etc/resolv.conf"))
(allow file-write* (subpath "/dev"))
'''
    policy+='(allow file-read* '+read+')\n'
    policy+='(allow file-read* file-write* (subpath '+literal(workspace)+'))\n'
    return ['/usr/bin/sandbox-exec','-p',policy,*argv]
