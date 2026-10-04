"""Reactor docgen path constants."""

from __future__ import annotations

import os
from pathlib import Path

# 优先使用显式配置，其次兼容旧环境变量，最后落到当前用户目录。
REACTOR_DOCGEN_HOME = Path(
    os.getenv("REACTOR_DOCGEN_HOME")
    or os.getenv("LEAGENT_HOME")
    or (Path.home() / ".reactor-docgen")
)
FONTS_DIR = REACTOR_DOCGEN_HOME / "fonts"
UPLOAD_DIR = Path(
    os.getenv("REACTOR_DOCGEN_UPLOAD_DIR") or (REACTOR_DOCGEN_HOME / "uploads")
)
KNOWLEDGE_DIR = Path(
    os.getenv("REACTOR_DOCGEN_KNOWLEDGE_DIR") or (REACTOR_DOCGEN_HOME / "knowledge")
)
TEMPLATE_STYLES_DIR = REACTOR_DOCGEN_HOME / "templates" / "styles"
OUTPUT_DIR = Path(
    os.getenv("REACTOR_DOCGEN_OUTPUT_DIR") or (Path.cwd() / "skilloutput" / "docgen")
)

for _p in (FONTS_DIR, UPLOAD_DIR, KNOWLEDGE_DIR, TEMPLATE_STYLES_DIR, OUTPUT_DIR):
    try:
        # 目录创建是启动期 best-effort；权限不足时保留路径配置，让具体工具返回可诊断错误。
        _p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


class _FilesSettings:
    upload_dir = str(UPLOAD_DIR)

    def resolved_knowledge_storage_dir(self):
        # 通过方法暴露稳定接口，避免调用方依赖内部 Path 常量。
        return str(KNOWLEDGE_DIR)


class _Settings:
    files = _FilesSettings()


def get_settings():
    """返回与现有工具调用约定兼容的轻量 settings 对象。"""
    return _Settings()


def configuration_dir(kind: str, shared: bool = False) -> Path:
    """Protected deployment: original shared configs are read-only for visitors."""
    root=Path(os.getenv('REACTOR_DOCGEN_HOME') or os.getenv('LEAGENT_HOME') or str(Path.home()/'.reactor-docgen'))
    if not shared and os.getenv('REACTOR_TOOL_AUTH_REQUIRED','false').lower()=='true':
        from reactor_tool.util.internal_auth import scoped_identity
        import hashlib
        visitor=scoped_identity()['visitor']
        root=root/'visitors'/hashlib.sha256(visitor.encode()).hexdigest()
    return root/'templates'/kind


def configuration_dirs(kind: str) -> list[Path]:
    local=configuration_dir(kind);shared=configuration_dir(kind,True)
    return [local] if local==shared else [local,shared]


def configuration_files(kind: str) -> list[Path]:
    found={}
    for directory in configuration_dirs(kind):
        if directory.is_dir():
            for path in sorted(directory.glob('*.y*ml')):found.setdefault(path.stem,path)
    return list(found.values())
