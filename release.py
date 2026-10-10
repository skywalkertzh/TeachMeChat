"""Local source-only release. No discovery, runtime collection, uploads or installs.

Run with the existing E-drive venv: python -B release.py --build
Only explicitly listed files are read. New source files require review here.
A manifest proves archive bytes, NOT that dependency licenses were audited.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
import zipfile


SOURCE_ALLOWLIST = (
    '.gitignore',
    'LICENSE',
    'README.md',
    'README-UPSTREAM.md',
    'Start-TeachMeChat.ps1',
    'Install-TeachMeChat-ASR.ps1',
    'TeachMeChat.pyw',
    'release.py',
    'teachmechat/__init__.py',
    'teachmechat/__main__.py',
    'teachmechat/app.py',
    'teachmechat/coach.py',
    'teachmechat/console.py',
    'teachmechat/credentials.py',
    'teachmechat/discovery.py',
    'teachmechat/download_model.py',
    'teachmechat/key_worker.py',
    'teachmechat/media.py',
    'teachmechat/models.py',
    'teachmechat/providers.py',
    'teachmechat/model_catalog.py',
    'teachmechat/provider_specs.py',
    'teachmechat/runtime.py',
    'teachmechat/scheduler.py',
    'teachmechat/services.py',
    'teachmechat/settings.py',
    'teachmechat/requirements.txt',
    'teachmechat/requirements-lock.txt',
    'teachmechat/DESIGN.md',
    'teachmechat/README.md',
    'teachmechat/VERIFICATION.md',
    'teachmechat/RELEASE_AUDIT.md',
    'teachmechat/THIRD_PARTY.md',
    'teachmechat/LICENSE',
    'teachmechat/NOTICE.md',
    'teachmechat/CONTRIBUTING.md',
    'teachmechat/SECURITY.md',
    'teachmechat/CHANGELOG.md',
    'teachmechat/PUBLISHING.md',
    'teachmechat/WECHAT_COMPAT.md',
    'teachmechat/PROMO.md',
    'teachmechat/Preview-Desktop.ps1',
    'teachmechat/sources/__init__.py',
    'teachmechat/sources/database.py',
    'teachmechat/sources/parsing.py',
    'teachmechat/desktop/__init__.py',
    'teachmechat/desktop/tasks.py',
    'teachmechat/context_options.py',
    'teachmechat/desktop/advice_view.py',
    'teachmechat/desktop/refresh_controls.py',
    'teachmechat/desktop/connect_button.py',
    'teachmechat/desktop/status_robot.py',
    'teachmechat/desktop/theme.py',
    'teachmechat/desktop/chrome.py',
    'teachmechat/desktop/chat_view.py',
    'teachmechat/desktop/message_format.py',
    'teachmechat/desktop/dialogs.py',
    'teachmechat/desktop/preview.py',
    'teachmechat/desktop/window.py',
    'teachmechat/desktop/workers.py',
    'teachmechat/tests/test_app.py',
    'teachmechat/tests/test_coach.py',
    'teachmechat/tests/test_console.py',
    'teachmechat/tests/test_discovery.py',
    'teachmechat/tests/test_desktop.py',
    'teachmechat/tests/test_desktop_dialogs.py',
    'teachmechat/tests/test_chat_scroll.py',
    'teachmechat/tests/test_refresh_controls.py',
    'teachmechat/tests/test_context_limits.py',
    'teachmechat/tests/test_theme.py',
    'teachmechat/tests/test_status_robot.py',
    'teachmechat/tests/test_settings.py',
    'teachmechat/tests/test_model_catalog.py',
    'teachmechat/tests/test_window_chrome.py',
    'teachmechat/tests/test_provider_specs.py',
    'teachmechat/tests/test_message_format.py',
    'teachmechat/tests/test_media.py',
    'teachmechat/tests/test_providers.py',
    'teachmechat/tests/test_runtime_scheduler.py',
    'teachmechat/tests/test_sources.py',
    'teachmechat/tests/test_release.py',
    # key_worker loads these directly with isolated package stubs; including
    # wxManager/__init__.py would import unrelated database/export subsystems.
    'wxManager/decrypt/common.py',
    'wxManager/decrypt/wx_info_v3.py',
    'wxManager/decrypt/wx_info_v4.py',
    'wxManager/decrypt/version_list.json',
    'wxManager/decrypt/decrypt_dat.py',
)
MANIFEST_NAME = 'MANIFEST.json'
ARCHIVE_NAME = 'teachmechat-source.zip'
LICENSE_NOTICE = ('Source archive only. LICENSE is included; third-party dependency '
                  'licenses have not all been audited. No dependencies are bundled.')
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024


class ReleaseError(ValueError):
    pass


def _safe_name(name: str) -> bool:
    """Defense in depth even if the explicit allowlist is edited incorrectly."""
    path = PurePosixPath(name)
    parts = tuple(part.casefold() for part in path.parts)
    if (not name or '\\' in name or ':' in name or path.is_absolute()
            or path.as_posix() != name or any(part in ('.', '..') for part in parts)):
        return False
    blocked = {'.teachmechat-runtime', '.git', '__pycache__', 'data', 'runtime',
               'venv', '.venv', 'cache', 'tmp', 'temp', 'logs', 'exports'}
    if any(part in blocked or part.startswith(('wxid_', 'synthetic_', '.env'))
           or '_decrypted_' in part for part in parts):
        return False
    if path.name in ('LICENSE', '.gitignore'):
        return len(parts) == 1 or name == 'teachmechat/LICENSE'
    if path.suffix.lower() == '.txt':
        return name in ('teachmechat/requirements.txt', 'teachmechat/requirements-lock.txt')
    if path.suffix.lower() == '.json':
        return name == 'wxManager/decrypt/version_list.json'
    return path.suffix.lower() in ('.py', '.pyw', '.md', '.ps1')


def _no_links(path: Path):
    # Reject Windows junctions/reparse points as well as POSIX symlinks.
    for component in (*reversed(path.parents), path):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ReleaseError('Release inputs and output must not use links or junctions.')


def validate_sources(root: Path) -> tuple[str, ...]:
    """Probe only named inputs; never list the repository or runtime directory."""
    root = Path(root).absolute()
    names = tuple(SOURCE_ALLOWLIST)
    if len({name.casefold() for name in names}) != len(names):
        raise ReleaseError('Duplicate source allowlist entry.')
    total = 0
    for name in names:
        if not _safe_name(name):
            raise ReleaseError('Unsafe source allowlist entry.')
        path = root / name
        _no_links(path)
        if not path.is_file():
            raise ReleaseError(f'Missing allowlisted source file: {name}')
        size = path.stat().st_size
        total += size
        if size > MAX_SOURCE_BYTES or total > MAX_TOTAL_BYTES:
            raise ReleaseError('Source archive exceeds the configured size limit.')
    return names


def build_archive(root: Path) -> Path:
    """Build locally when explicitly invoked; default output is runtime/release."""
    root = Path(root).absolute()
    _no_links(root)
    if os.name == 'nt' and (not root.is_absolute() or str(root.drive) == '' or root.drive.startswith('\\\\')):
        raise ReleaseError('Release output and temporary files must stay on a local absolute path.')
    names = validate_sources(root)
    output = root / '.teachmechat-runtime' / 'release'
    _no_links(output)
    output.mkdir(parents=True, exist_ok=True)
    target = output / ARCHIVE_NAME
    _no_links(target)
    descriptor, temporary = tempfile.mkstemp(prefix='source-', suffix='.tmp', dir=output)
    os.close(descriptor)
    temporary = Path(temporary)
    try:
        entries = []
        total = 0
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name in names:
                path = root / name
                _no_links(path)
                with path.open('rb') as stream:
                    data = stream.read(MAX_SOURCE_BYTES + 1)
                total += len(data)
                if len(data) > MAX_SOURCE_BYTES or total > MAX_TOTAL_BYTES:
                    raise ReleaseError('Source archive exceeds the configured size limit.')
                archive.writestr(name, data)
                entries.append({'path': name, 'size': len(data),
                                'sha256': hashlib.sha256(data).hexdigest()})
            manifest = {'format': 1, 'algorithm': 'sha256', 'files': entries,
                        'scope': 'Explicit source allowlist; no runtime or account data.',
                        'dependency_license_audit': 'not_performed',
                        'notice': LICENSE_NOTICE}
            archive.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False,
                                                      indent=2).encode('utf-8'))
        os.replace(temporary, target)
        return target
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--build', action='store_true', help='Create a local source ZIP in the project runtime directory. No upload.')
    action.add_argument('--check', action='store_true', help='Validate named source paths only; do not build.')
    options = parser.parse_args(argv)
    if not options.build and not options.check:
        parser.print_help()
        return 0
    root = Path(__file__).absolute().parent
    try:
        if options.check:
            print(f'Allowlist OK: {len(validate_sources(root))} source files. No archive created.')
        else:
            print(f'Local source archive: {build_archive(root)}')
        print(LICENSE_NOTICE)
        return 0
    except (ReleaseError, OSError, zipfile.BadZipFile) as exc:
        print(f'Release failed: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
