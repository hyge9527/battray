#!/usr/bin/env python3
"""Create a fresh, reviewable source export; never initializes Git or publishes."""

from datetime import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROOT_FILES = ('.gitignore', 'README.md', 'readme_rebuild.md', 'prompt_rebuild.md',
              'prompt.md', 'VALIDATION.md', 'CONTRIBUTING.md', 'THIRD_PARTY_NOTICES.md', 'LICENSE')
DIRECTORIES = ('keyboard_power', 'tests', 'tools', 'packaging', 'prompts', 'docs', '.github')
SUFFIXES = {'.py', '.md', '.json', '.js', '.mjs', '.rules', '.yml', '.yaml', '.toml'}
EXCLUDED = {'docs/review-baseline.json', 'docs/review-changes.patch'}
SKIP_PARTS = {'__pycache__', '.git', '.backups', '.publish', '.venv', 'node_modules'}


def source_files(root):
    sources = {}
    for name in ROOT_FILES:
        path = root / name
        if path.is_symlink():
            raise ValueError('拒绝跟随导出文件的符号链接：' + name)
        if path.is_file():
            sources[name] = path
    for name in DIRECTORIES:
        directory = root / name
        if directory.is_symlink():
            raise ValueError('拒绝跟随导出目录的符号链接：' + name)
        if not directory.exists():
            continue
        for path in directory.rglob('*'):
            relative = path.relative_to(root)
            if any(part in SKIP_PARTS for part in relative.parts) or str(relative) in EXCLUDED:
                continue
            if path.is_symlink():
                raise ValueError('拒绝跟随导出符号链接：' + str(relative))
            if path.is_file() and path.suffix in SUFFIXES:
                sources[str(relative)] = path
    return sources


def prepare(root=ROOT):
    sources = source_files(root)
    if 'my_devices.py' not in sources:
        # The executable entry is intentionally separate from package directories.
        entry = root / 'my_devices.py'
        if entry.is_symlink() or not entry.is_file():
            raise ValueError('缺少可导出的普通入口文件 my_devices.py')
        sources['my_devices.py'] = entry
    output = root / '.publish' / ('github-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    if (root / '.publish').is_symlink():
        raise ValueError('拒绝写入符号链接发布目录')
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for name, source in sorted(sources.items()):
        data = source.read_bytes()
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(data)
        target.chmod(source.stat().st_mode & 0o777)
        assert target.read_bytes() == data, name
        records.append(dict(path=name, size=len(data), sha256=hashlib.sha256(data).hexdigest()))
    manifest = dict(files=records, file_count=len(records),
                    license_present='LICENSE' in sources,
                    review_required=['manual privacy review', 'upstream provenance/permission review', 'project license selection'])
    (output / 'PUBLISH_MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return output, manifest


if __name__ == '__main__':
    path, manifest = prepare()
    print(json.dumps(dict(directory=str(path), files=manifest['file_count'],
                          license_present=manifest['license_present'],
                          status='review copy only; no git initialization or upload'), ensure_ascii=False))
