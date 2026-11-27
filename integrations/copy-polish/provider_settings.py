"""Recipient-owned Gemini-compatible settings. No credentials, transport or writes."""
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

FIELDS={'schema_version','api_family','origin','model','key_env','diagnostic_root'}


def unlinked(path):
    for node in (path,*path.parents):
        if node.is_symlink() or node.exists() and getattr(node.lstat(),'st_file_attributes',0) & 0x400:
            raise ValueError('linked_provider_configuration_denied')


def external(path, package):
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('absolute_private_provider_path_required')
    unlinked(path)
    value=path.resolve()
    if value==package or value.is_relative_to(package):
        raise ValueError('provider_state_must_be_outside_tool_package')
    return value


def load(path, package_root):
    package=Path(package_root).resolve()
    path=external(Path(path),package)
    if not path.is_file() or path.stat().st_size>65536:
        raise ValueError('invalid_provider_configuration_file')
    value=json.loads(path.read_text(encoding='utf-8-sig'))
    if (not isinstance(value,dict) or value.keys()!=FIELDS or type(value['schema_version']) is not int
            or value['schema_version']!=1 or value['api_family']!='gemini-generate-content'):
        raise ValueError('unsupported_provider_configuration')
    origin=value['origin']
    if not isinstance(origin,str) or origin!=origin.strip():
        raise ValueError('invalid_provider_origin')
    parsed=urlsplit(origin)
    try:
        valid=(parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password
               and parsed.path in ('','/') and not parsed.query and not parsed.fragment
               and '%' not in parsed.netloc and parsed.port!=0 and origin.isascii())
    except ValueError:
        valid=False
    if not valid:raise ValueError('provider_origin_must_be_explicit_https_origin')
    model=value['model'];key_env=value['key_env']
    if (not isinstance(model,str) or not 1<=len(model)<=160 or model!=model.strip()
            or any(ord(c)<32 or ord(c)==127 for c in model)):
        raise ValueError('explicit_recipient_model_required')
    if not isinstance(key_env,str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,95}_API_KEY',key_env):
        raise ValueError('explicit_api_key_environment_name_required')
    if not isinstance(value['diagnostic_root'],str):raise ValueError('invalid_private_diagnostic_root')
    diagnostic=external(Path(value['diagnostic_root']),package)
    if not diagnostic.is_dir():raise ValueError('create_private_diagnostic_root_before_live_call')
    return dict(value,origin=origin.rstrip('/'),diagnostic_root=str(diagnostic))
