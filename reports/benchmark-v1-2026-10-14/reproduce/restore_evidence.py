#!/usr/bin/env python3
"""Verify and restore the original GitHub evidence ZIP into a fresh directory."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile


def restore(archive, metadata, output):
    if archive.is_symlink() or metadata.is_symlink() or not archive.is_file():
        raise ValueError('Expected regular archive and metadata files')
    if output.exists() or output.is_symlink() or any(p.is_symlink() for p in output.parents):
        raise ValueError('Choose a fresh output without symlink parents')
    info = json.loads(metadata.read_text())
    if archive.stat().st_size != info['bytes'] or archive.stat().st_size > 50_000_000:
        raise ValueError('Archive size differs from preserved GitHub metadata')
    if hashlib.sha256(archive.read_bytes()).hexdigest() != info['sha256']:
        raise ValueError('Archive checksum differs from preserved GitHub metadata')
    with zipfile.ZipFile(archive) as z:
        members = z.infolist()
        if len(members) > 15000 or sum(m.file_size for m in members) > 300_000_000:
            raise ValueError('Expanded archive exceeds its bound')
        names = set()
        for member in members:
            path = PurePosixPath(member.filename)
            if (path.is_absolute() or '..' in path.parts or '\\' in member.filename
                    or not path.parts or member.filename in names
                    or stat.S_ISLNK(member.external_attr >> 16)):
                raise ValueError('Unsafe or duplicate archive member')
            names.add(member.filename)
            if path.name == 'private-kubeconfig' or path.suffix.lower() in ('.key', '.pem', '.gguf'):
                raise ValueError('Unexpected credential or model binary')
        output.mkdir(parents=True, exist_ok=False)
        z.extractall(output)
    print(json.dumps({'status': 'restored', 'sha256_verified': True,
                      'files': len(members), 'output': str(output)}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--metadata', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    try:
        restore(args.archive, args.metadata, args.output)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        p.exit(2, f'Restore refused: {exc}\n')
