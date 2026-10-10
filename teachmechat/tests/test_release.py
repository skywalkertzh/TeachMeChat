"""Release tests use a synthetic local source tree, never the real runtime."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import release


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='synthetic_release_', dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        for name in release.SOURCE_ALLOWLIST:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('synthetic source: ' + name).encode())

    def test_explicit_allowlist_manifest_and_fake_sensitive_markers(self):
        marker = b'SYNTHETIC_PRIVATE_DO_NOT_SHIP_83d74a'
        excluded = (
            '.teachmechat-runtime/settings.json',
            '.teachmechat-runtime/cache/secrets.py',
            '.teachmechat-runtime/venv/secret.py',
            '.teachmechat-runtime/release/old.zip',
            'wxid_fake/Msg/MSG0.db',
            'wxid_fake_decrypted_20260101/MSG0.db',
            'data/chat.txt', 'private.key', '.env', 'session.log',
            'teachmechat/private.py', 'teachmechat/tests/private_fixture.json',
            'wxManager/decrypt/private.py',
        )
        for name in excluded:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(marker)
        with patch('os.scandir', side_effect=AssertionError('directory scan forbidden')), \
             patch.object(Path, 'rglob', side_effect=AssertionError('recursive scan forbidden')):
            archive_path = release.build_archive(self.root)
        # 归档仍写在项目 runtime 的 release 目录下，且必须是本机绝对路径。
        self.assertEqual(archive_path.parent, self.root / '.teachmechat-runtime/release')
        self.assertTrue(archive_path.is_absolute())
        self.assertEqual(archive_path.drive, self.root.drive)
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            self.assertEqual(set(names), set(release.SOURCE_ALLOWLIST) | {release.MANIFEST_NAME})
            self.assertEqual(len(names), len(set(names)))
            manifest = json.loads(archive.read(release.MANIFEST_NAME))
            self.assertEqual(manifest['dependency_license_audit'], 'not_performed')
            self.assertEqual({item['path'] for item in manifest['files']}, set(release.SOURCE_ALLOWLIST))
            for item in manifest['files']:
                data = archive.read(item['path'])
                self.assertEqual(hashlib.sha256(data).hexdigest(), item['sha256'])
                self.assertEqual(len(data), item['size'])
            for name in names:
                self.assertNotIn(marker, archive.read(name))
        self.assertFalse(list(archive_path.parent.glob('*.tmp')))

    def test_only_build_flag_writes_archive(self):
        with patch.object(release, '__file__', str(self.root / 'release.py')), \
             contextlib.redirect_stdout(io.StringIO()), \
             patch.object(release, 'build_archive', wraps=release.build_archive) as build:
            self.assertEqual(release.main([]), 0)
            self.assertEqual(release.main(['--check']), 0)
            build.assert_not_called()
            self.assertFalse((self.root / '.teachmechat-runtime').exists())
            self.assertEqual(release.main(['--build']), 0)
            build.assert_called_once_with(self.root)

    def test_import_and_no_args_in_fresh_interpreter_do_not_build(self):
        # This copies only the public release script into the synthetic tree.
        script = Path(release.__file__).read_bytes()
        (self.root / 'release.py').write_bytes(script)
        result = subprocess.run([sys.executable, '-B', str(self.root / 'release.py')],
                                cwd=self.root, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b'--build', result.stdout)
        self.assertFalse((self.root / '.teachmechat-runtime').exists())

    def test_missing_or_oversize_inputs_fail_without_output(self):
        missing = self.root / release.SOURCE_ALLOWLIST[-1]
        missing.unlink()
        with self.assertRaisesRegex(release.ReleaseError, 'Missing'):
            release.build_archive(self.root)
        self.assertFalse((self.root / '.teachmechat-runtime').exists())
        missing.write_bytes(b'synthetic')
        with patch.object(release, 'MAX_SOURCE_BYTES', 1):
            with self.assertRaisesRegex(release.ReleaseError, 'size limit'):
                release.build_archive(self.root)
        self.assertFalse((self.root / '.teachmechat-runtime').exists())

    def test_allowlist_rejects_runtime_traversal_and_sensitive_extensions(self):
        for name in ('.teachmechat-runtime/cache/source.py', '../escape.py',
                     'teachmechat/../private.py', 'E:/private.py', '/private.py',
                     'wxid_fake/source.py', 'teachmechat/credentials.json',
                     'teachmechat/secret.key', 'teachmechat/chat.db',
                     'teachmechat/tests/synthetic_sources_fake/private.py'):
            with self.subTest(name=name), patch.object(release, 'SOURCE_ALLOWLIST', (name,)):
                with self.assertRaisesRegex(release.ReleaseError, 'Unsafe'):
                    release.build_archive(self.root)
        self.assertFalse((self.root / '.teachmechat-runtime').exists())

    def test_links_are_rejected_before_source_read(self):
        path = self.root / 'teachmechat/app.py'
        original = Path.lstat
        class ReparseInfo:
            st_mode = 0
            st_file_attributes = 0x400
        def lstat(candidate, *args, **kwargs):
            return ReparseInfo() if candidate == path else original(candidate, *args, **kwargs)
        with patch.object(Path, 'lstat', lstat):
            with self.assertRaisesRegex(release.ReleaseError, 'links or junctions'):
                release.build_archive(self.root)
        self.assertFalse((self.root / '.teachmechat-runtime').exists())

    def test_write_failure_cleans_only_own_temp_and_keeps_previous_zip(self):
        previous = release.build_archive(self.root)
        before = previous.read_bytes()
        with patch.object(zipfile.ZipFile, 'writestr', side_effect=OSError('synthetic failure')):
            with self.assertRaises(OSError):
                release.build_archive(self.root)
        self.assertEqual(previous.read_bytes(), before)
        self.assertEqual({p.name for p in previous.parent.iterdir()}, {release.ARCHIVE_NAME})

    def test_gitignore_keeps_tests_requirements_and_hides_runtime(self):
        git = shutil.which('git')
        if not git:
            self.skipTest('git unavailable')
        ignore = Path(release.__file__).parent / '.gitignore'
        (self.root / '.gitignore').write_bytes(ignore.read_bytes())
        subprocess.run([git, 'init', '-q', str(self.root)], check=True, capture_output=True, timeout=15)
        visible = ('teachmechat/tests/test_sources.py', 'teachmechat/tests/test_release.py',
                   'teachmechat/requirements.txt', 'teachmechat/requirements-lock.txt', 'requirements.txt',
                   'wxManager/decrypt/version_list.json')
        hidden = ('.teachmechat-runtime/cache/module.py', '.teachmechat-runtime/tmp/token.key',
                  'teachmechat/tests/synthetic_sources_fake/MSG0.db',
                  'teachmechat/tests/synthetic_release_fake/release.py',
                  'MSG0.db-wal', 'MSG0.db-shm', 'credentials.json', 'private.key')
        result = subprocess.run([git, 'check-ignore', '--no-index', '--stdin', '-z'],
                                input=('\0'.join(visible + hidden) + '\0').encode('utf-8'),
                                cwd=self.root, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        ignored = {item.decode('utf-8') for item in result.stdout.split(b'\0') if item}
        self.assertEqual(ignored, set(hidden))


if __name__ == '__main__':
    unittest.main()
