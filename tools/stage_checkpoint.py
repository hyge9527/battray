from pathlib import Path
from datetime import datetime
import argparse, difflib, hashlib, io, json, tarfile
EXCLUDED={'.backups','.git','.aws','.codex','.agents','__pycache__'}
def files(root):
    result = {}
    for path in root.rglob('*'):
        relative = path.relative_to(root)
        if any(part in EXCLUDED for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError('项目内符号链接须人工审阅备份，不读取链接目标：' + str(relative))
        if path.is_file():
            result[str(relative)] = path
    return result
def backup(root,label):
    folder=root/'.backups'/(label+'-'+datetime.now().strftime('%Y%m%d-%H%M%S')); folder.mkdir(parents=True)
    contents={n:(p.read_bytes(),p.stat().st_mode & 0o777) for n,p in files(root).items()}
    archive=folder/'project.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        for name,(data,mode) in sorted(contents.items()):
            entry=tarfile.TarInfo('project/'+name); entry.size=len(data); entry.mode=mode; tar.addfile(entry,io.BytesIO(data))
    with tarfile.open(archive) as tar:
        assert len(tar.getmembers())==len(contents)
        for name,(data,_) in contents.items():
            assert tar.extractfile('project/'+name).read()==data
            assert (root/name).read_bytes()==data
    manifest=dict(verified=True,file_count=len(contents),archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),files=[dict(path=n,size=len(d),mode=m,sha256=hashlib.sha256(d).hexdigest()) for n,(d,m) in sorted(contents.items())])
    (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    (folder/'RESTORE.md').write_text('# 阶段基线\n\n归档不含其他备份、缓存与环境挂载目录，也不含项目外设置。先退出应用并保存后续修改，校验 manifest.json 中的归档 SHA256，再解压到新的空目录并逐项比较恢复，勿直接覆盖当前项目。\n')
    (root/'.backups/LATEST').write_text(folder.name+'\n'); print(json.dumps(dict(backup=str(folder),files=len(contents),sha256=manifest['archive_sha256']),ensure_ascii=False))
def finish(root,stage,tests,baseline=None):
    name = baseline or (root/'.backups/LATEST').read_text().strip()
    if not name or name != Path(name).name or name in ('.', '..'):
        raise ValueError('Invalid baseline name')
    folder=root/'.backups'/name; manifest=json.loads((folder/'manifest.json').read_text()); archive=folder/'project.tar.gz'
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==manifest['archive_sha256']
    with tarfile.open(archive) as tar:
        old={m.name.removeprefix('project/'):tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
    for item in manifest['files']: assert hashlib.sha256(old[item['path']]).hexdigest()==item['sha256']
    current={n:p.read_bytes() for n,p in files(root).items()}; patch=[]; changed=[]
    for name in sorted(set(old)|set(current)):
        a,b=old.get(name,b''),current.get(name,b'')
        if a==b: continue
        changed.append(name)
        try: a,b=a.decode(),b.decode()
        except UnicodeDecodeError: continue
        patch.extend(difflib.unified_diff(a.splitlines(True),b.splitlines(True),fromfile='a/'+name if name in old else '/dev/null',tofile='b/'+name if name in current else '/dev/null'))
    (folder/f'phase-{stage}.patch').write_text(''.join(patch))
    (folder/f'phase-{stage}-verification.json').write_text(json.dumps(dict(stage=stage,reported_passing_tests=tests,baseline_sha256=manifest['archive_sha256'],changed_files=changed,patch_sha256=hashlib.sha256(''.join(patch).encode()).hexdigest()),ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(stage=stage,baseline=str(folder),changed_files=changed),ensure_ascii=False))
if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('action',choices=['backup','finish']); parser.add_argument('--label'); parser.add_argument('--stage',type=int); parser.add_argument('--tests',type=int); parser.add_argument('--baseline',help='指定历史基线目录名；默认 LATEST'); args=parser.parse_args(); root=Path.cwd()
    if not (root/'my_devices.py').is_file() or not (root/'keyboard_power').is_dir(): parser.error('Run from the project root')
    if args.action=='backup':
        if not args.label or not all(c.isalnum() or c in '-_' for c in args.label): parser.error('invalid label')
        backup(root,args.label)
    else:
        if args.stage is None or args.stage < 1 or args.tests is None or args.tests < 0: parser.error('finish requires --stage and --tests')
        finish(root,args.stage,args.tests,args.baseline)
