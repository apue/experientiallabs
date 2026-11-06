"""Treat dotenv files as data, never shell scripts."""
import os
import re
import shlex
from pathlib import Path


def load_key(path=None, name='EXPLABS_API_KEY'):
    if path is None:
        value = os.environ.get(name, '')
    else:
        value = ''
        for line in Path(path).expanduser().read_text(encoding='utf-8-sig').splitlines():
            match = re.match(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$', line)
            if not match or match[1] != name:
                continue
            try:
                parts = shlex.split(match[2], comments=True, posix=True)
            except ValueError:
                raise ValueError('Invalid quoting in API key assignment') from None
            if len(parts) != 1:
                raise ValueError('API key must be one nonempty value')
            value = parts[0]
    if not value or any(c.isspace() for c in value):
        raise ValueError(f'Missing or invalid {name}; use --env-file PATH and optionally --key-name NAME')
    return value
