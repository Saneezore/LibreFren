#!/usr/bin/env python3
"""Build from caller-provided, hash-pinned packaging tools. No implicit downloads."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--appimagetool', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--tool-sha256', required=True)
    parser.add_argument('--runtime-sha256', required=True)
    args = parser.parse_args()
    for path, expected in ((args.appimagetool, args.tool_sha256), (args.runtime, args.runtime_sha256)):
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise SystemExit('Packaging tool hash mismatch: ' + str(path))
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
                    '--name', 'librefren', '--paths', str(ROOT),
                    '--add-data', str(ROOT / 'librefren/data') + ':librefren/data',
                    '--distpath', str(ROOT / 'build/frozen'), '--workpath', str(ROOT / 'build/pyinstaller'),
                    '--specpath', str(ROOT / 'build'), str(ROOT / 'packaging/entrypoint.py')], check=True, cwd=ROOT,
                   env=dict(os.environ, PYINSTALLER_CONFIG_DIR=str(ROOT / 'build/pyinstaller-cache')))
    appdir = ROOT / 'build/LibreFren.AppDir'
    appdir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / 'build/frozen/librefren', appdir / 'usr/bin', dirs_exist_ok=True)
    for name in ('librefren.desktop', 'librefren.svg'):
        shutil.copyfile(ROOT / 'packaging' / name, appdir / name)
    notices = appdir / 'usr/share/doc/librefren'
    notices.mkdir(parents=True, exist_ok=True)
    for name in ('LICENSE', 'THIRD_PARTY.md', 'README.md'):
        shutil.copyfile(ROOT / name, notices / name)
    for name in ('python3.11', 'python3.13', 'libpython3.11', 'libpython3.13', 'libncursesw6', 'libtinfo6', 'libsqlite3-0', 'libffi8', 'zlib1g', 'libbz2-1.0', 'liblzma5', 'libssl3', 'libssl3t64'):
        copyright_file = Path('/usr/share/doc') / name / 'copyright'
        if copyright_file.is_file():
            shutil.copyfile(copyright_file, notices / (name + '-copyright'))
    launch = appdir / 'AppRun'
    launch.write_text('#!/bin/sh\nAPPDIR="$(dirname "$(readlink -f "$0")")"\nexec "$APPDIR/usr/bin/librefren" "$@"\n')
    launch.chmod(0o755)
    output = ROOT / 'dist/LibreFren-0.1.0-x86_64.AppImage'
    output.parent.mkdir(exist_ok=True)
    env = dict(os.environ, ARCH='x86_64', APPIMAGE_EXTRACT_AND_RUN='1')
    subprocess.run([str(args.appimagetool.resolve()), '--runtime-file', str(args.runtime.resolve()), str(appdir), str(output)], env=env, check=True)
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.AppImage.sha256').write_text(checksum + '  ' + output.name + '\n')
    print(output)


if __name__ == '__main__':
    main()
