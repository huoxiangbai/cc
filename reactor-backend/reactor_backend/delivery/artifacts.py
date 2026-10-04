import mimetypes
from urllib.parse import urlparse, unquote
from reactor_backend.models.types import encode


def artifact_values(run, tool_id, call, f):
    name = f.get("fileName") or f.get("file_name")
    if not name:
        raise ValueError("Tool fileInfo missing fileName")
    download = f.get("downloadUrl") or f.get("ossUrl") or f.get("oss_url")
    preview = f.get("previewUrl") or f.get("domainUrl") or f.get("domain_url")
    # The real Tool file service must provide public URLs. Never publish a local absolute path.
    if not download or not preview or any(urlparse(u).scheme not in ("http", "https") and not u.startswith("/tool/") for u in (download, preview)):
        raise ValueError("Tool artifact has no usable HTTP preview/download reference")
    key = f.get("storageKey") or download or preview or name
    return dict(run_id=run["id"], request_id=run["request_id"], tool_invocation_id=tool_id,
                tool_call_id=call.id, artifact_role="output", visibility="visible", source_type="tool_output",
                source_name=call.name, file_name=name, storage_key=key, download_url=download,
                preview_url=preview, mime_type=f.get("mimeType") or mimetypes.guess_type(name)[0],
                file_size=f.get("fileSize", f.get("file_size")), metadata_json=encode(f))


def artifact_ref(a):
    name = a["file_name"]
    metadata = a.get("metadata_json")
    import json
    try: meta = json.loads(metadata) if isinstance(metadata,str) and metadata else metadata or {}
    except ValueError: meta = {}
    if not isinstance(meta,dict): meta = {}
    origin = meta.get("originFileName") or ""
    description = meta.get("description") or ""
    relative = meta.get("relativePath") or (origin if "/" in origin or "\\" in origin else None) or (description[10:] if description.startswith("workspace:") else None) or name
    relative = relative.replace("\\","/").strip()
    while relative.startswith("./"): relative = relative[2:]
    relative = relative.lstrip("/")
    return dict(resourceKey=a.get("storage_key") or name, name=name, previewUrl=a.get("preview_url"),
                downloadUrl=a.get("download_url"), fileName=name, relativePath=relative,
                originFileName=relative, mimeType=a.get("mime_type"), size=a.get("file_size"), missing=False)
