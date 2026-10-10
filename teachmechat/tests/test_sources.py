"""Synthetic databases only. All fixtures live beside this test on E:.
Run with the project's existing E-drive interpreter and python -B.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic
from unittest.mock import patch

from teachmechat.models import TeachMeChatError
from teachmechat.sources import SnapshotSource, LiveWeChatSource, create_source, discover_accounts
from teachmechat.sources.database import (
    CONTENT_PLACEHOLDER, MAX_CONTENT, MAX_VOICE_BYTES, database_files,
    derive_raw_key, quote_identifier,
)
from teachmechat.sources.parsing import v4_packed


V3_SCHEMA = '''CREATE TABLE MSG(localId INTEGER, StrTalker TEXT, CreateTime INTEGER,
 Type INTEGER, IsSender INTEGER, StrContent TEXT, CompressContent BLOB,
 MsgSvrID INTEGER, BytesExtra BLOB, DisplayContent TEXT)'''


def v3_row(connection, local_id, timestamp=100, talker='friend', text=None, kind=1):
    connection.execute('INSERT INTO MSG VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (local_id, talker, timestamp, kind, 0, text or f'msg-{local_id}',
                        None, local_id + 10000, None, None))


def v4_schema(connection, user='friend'):
    table = 'Msg_' + hashlib.md5(user.encode()).hexdigest()
    connection.execute('CREATE TABLE Name2Id(user_name TEXT)')
    connection.executemany('INSERT INTO Name2Id VALUES(?)', [('friend',), ('self',)])
    connection.execute(f'''CREATE TABLE {table}(local_id INTEGER, server_id INTEGER,
        local_type INTEGER, sort_seq INTEGER, real_sender_id INTEGER, create_time INTEGER,
        message_content BLOB, compress_content BLOB, packed_info_data BLOB)''')
    return table


def proto_bytes(field, value):
    def varint(number):
        result = bytearray()
        while number > 127:
            result.append((number & 127) | 128)
            number >>= 7
        result.append(number)
        return bytes(result)
    return varint(field * 8 + 2) + varint(len(value)) + value


class SourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='synthetic_sources_', dir=Path(__file__).parent)
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def make_v3(self, name='MSG0.db'):
        path = self.root / name
        connection = sqlite3.connect(path)
        connection.execute(V3_SCHEMA)
        return path, connection

    def test_cross_shard_same_second_and_larger_page(self):
        for shard in range(3):
            _, writer = self.make_v3(f'MSG{shard}.db')
            for number in range(90):
                v3_row(writer, number, 100, text=f'{shard}-{number}')
            v3_row(writer, 999, 101, talker=f'new-{shard}')
            writer.commit()
            writer.close()
        source = SnapshotSource(self.root, 3)
        self.addCleanup(source.close)
        messages = source.recent('friend')
        self.assertEqual(len(messages), 100)
        self.assertEqual([m.id for m in messages], [m.id for m in source.recent('friend')])
        self.assertEqual(len({m.id for m in source.recent('friend', 300)}), 270)
        self.assertEqual([m.id for m in messages], [m.id for m in source.recent('friend', 170)[-100:]])
        self.assertEqual([c.timestamp for c in source.list_conversations()], [101, 101, 101, 100])
        with ThreadPoolExecutor(max_workers=1) as pool:
            self.assertEqual(len(pool.submit(source.recent, 'friend').result()), 100)

    def test_contacts_sql_injection_and_read_only(self):
        path, writer = self.make_v3()
        v3_row(writer, 1)
        writer.execute('CREATE TABLE Contact(UserName TEXT, Remark TEXT, NickName TEXT, Alias TEXT)')
        writer.execute('INSERT INTO Contact VALUES(?,?,?,?)', ('friend', '朋友', '昵称', 'alias'))
        writer.commit()
        writer.close()
        before = path.read_bytes()
        source = SnapshotSource(self.root, 3)
        self.addCleanup(source.close)
        self.assertEqual(source.search_contacts('ALIAS')[0].name, '朋友')
        self.assertEqual(source.recent("x' OR 1=1--"), [])
        self.assertEqual(quote_identifier('a"b'), '"a""b"')
        with self.assertRaises(TeachMeChatError):
            source._select(path, 'CREATE INDEX nope ON MSG(localId)')
        connection = source._connect(path)
        with self.assertRaises(sqlite3.DatabaseError):
            connection.execute('DELETE FROM MSG')
        connection.close()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(set(p.name for p in self.root.iterdir()), {'MSG0.db'})

    def test_snapshot_uncheckpointed_wal_and_no_mutation(self):
        path, writer = self.make_v3()
        writer.commit()
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        v3_row(writer, 1, 10)
        writer.commit()
        self.addCleanup(writer.close)
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if not p.name.endswith('-shm')}
        source = SnapshotSource(self.root, 3)
        self.assertEqual(source.recent('friend')[0].timestamp, 10)
        v3_row(writer, 2, 20)
        writer.commit()
        self.assertEqual([m.timestamp for m in source.recent('friend')], [10, 20])
        after_insert = {p.name: p.read_bytes() for p in self.root.iterdir() if not p.name.endswith('-shm')}
        source.list_conversations()
        source.close()
        self.assertEqual(after_insert, {p.name: p.read_bytes() for p in self.root.iterdir() if not p.name.endswith('-shm')})
        self.assertEqual(before[path.name], path.read_bytes())

    def test_wal_missing_shm_refuses_without_creating(self):
        path, writer = self.make_v3()
        writer.commit()
        writer.close()
        Path(str(path) + '-wal').write_bytes(b'synthetic-incomplete-wal')
        with self.assertRaisesRegex(TeachMeChatError, 'SHM'):
            SnapshotSource(self.root, 3)
        self.assertFalse(Path(str(path) + '-shm').exists())

    def test_v3_voice_and_image_metadata(self):
        _, writer = self.make_v3()
        (self.root / 'photo.dat').write_bytes(b'image')
        (self.root / 'thumb.dat').write_bytes(b'thumb')
        v3_row(writer, 1, text='<msg><img path="photo.dat" thumbpath="thumb.dat" xor_key="42"/></msg>', kind=3)
        v3_row(writer, 2, text='<msg><voicemsg voicelength="1000"/><voicetrans transtext="合成转写"/></msg>', kind=34)
        writer.execute('CREATE TABLE Media(Reserved0 INTEGER, Buf BLOB)')
        writer.execute('INSERT INTO Media VALUES(?,?)', (10002, b'#!SILK_V3synthetic'))
        writer.commit()
        writer.close()
        source = SnapshotSource(self.root, 3, self.root)
        self.addCleanup(source.close)
        image, voice = source.recent('friend')
        self.assertEqual(image.metadata['xor_key'], 42)
        self.assertEqual(image.metadata['thumbnail_path'], str(self.root / 'thumb.dat'))
        self.assertEqual(image.media_path, str(self.root / 'photo.dat'))
        self.assertEqual(voice.metadata['wechat_transcript'], '合成转写')
        self.assertEqual(voice.media_bytes, b'#!SILK_V3synthetic')

    def test_v4_zstd_and_packed_images_and_voice(self):
        import zstandard
        path = self.root / 'message_0.db'
        writer = sqlite3.connect(path)
        table = v4_schema(writer)
        timestamp = 1735689600
        compressed = zstandard.ZstdCompressor().compress('合成压缩文本'.encode())
        writer.execute(f'INSERT INTO {table} VALUES(1,101,1,10,2,?,?,NULL,NULL)', (timestamp, compressed))
        image_packed = proto_bytes(3, proto_bytes(4, b'synthetic-picture'))
        audio_packed = proto_bytes(5, proto_bytes(2, '已有转写'.encode()))
        writer.execute(f'INSERT INTO {table} VALUES(2,102,3,11,1,?,?,NULL,?)', (timestamp, '<msg><img/></msg>', image_packed))
        writer.execute(f'INSERT INTO {table} VALUES(3,103,34,12,1,?,?,NULL,?)', (timestamp, '<msg><voicemsg/></msg>', audio_packed))
        writer.commit()
        writer.close()
        from datetime import datetime
        folder = self.root / 'msg' / 'attach' / hashlib.md5(b'friend').hexdigest() / datetime.fromtimestamp(timestamp).strftime('%Y-%m') / 'Img'
        folder.mkdir(parents=True)
        (folder / 'synthetic-picture_W.dat').write_bytes(b'synthetic')
        (folder / 'synthetic-picture_t.dat').write_bytes(b'synthetic')
        source = create_source(self.root, 4, media_root=self.root, account_id='self')
        self.addCleanup(source.close)
        text, image, voice = source.recent('friend')
        self.assertEqual(text.text, '合成压缩文本')
        self.assertTrue(text.outgoing)
        self.assertTrue(image.media_path.endswith('synthetic-picture_W.dat'))
        self.assertTrue(image.metadata['thumbnail_path'].endswith('synthetic-picture_t.dat'))
        self.assertEqual(voice.text, '已有转写')
        self.assertEqual(source.list_conversations()[0].id, 'friend')
        self.assertEqual(v4_packed(proto_bytes(3, b'old-filename'))['filename'], 'old-filename')

    def test_explicit_discovery_errors_and_no_wxmanager_import(self):
        self.assertEqual(discover_accounts(), [])
        with patch('teachmechat.sources.database.database_files', side_effect=AssertionError):
            self.assertEqual(discover_accounts([self.root]), [])
        with self.assertRaises(TeachMeChatError):
            SnapshotSource(self.root, 2)
        with self.assertRaises(TeachMeChatError) as caught:
            LiveWeChatSource(self.root, 3, 'SECRET-invalid-key')
        self.assertNotIn('SECRET', str(caught.exception))
        self.assertNotIn('wxManager', sys.modules)

    def test_live_driver_missing_safe_error(self):
        with patch('teachmechat.sources.database.importlib.import_module', side_effect=ImportError):
            with self.assertRaisesRegex(TeachMeChatError, 'SQLCipher'):
                LiveWeChatSource(self.root, 3, '12' * 32)

    def test_long_sql_cancelled_during_execute_and_fetch(self):
        path, writer = self.make_v3()
        writer.commit()
        writer.close()
        source = SnapshotSource(self.root, 3, query_timeout_seconds=0.03)
        self.addCleanup(source.close)
        before = path.read_bytes()
        for projection in ('sum(x)', 'x'):
            sql = ('SELECT ' + projection + ' FROM (WITH RECURSIVE work(x) AS '
                   '(SELECT 1 UNION ALL SELECT x+1 FROM work WHERE x<1000000000) '
                   'SELECT x FROM work)')
            started = monotonic()
            with self.assertRaisesRegex(TeachMeChatError, '时间预算'):
                source._select(path, sql)
            self.assertLess(monotonic() - started, 2)
            self.assertEqual(source._select(path, 'SELECT 1'), [(1,)])
        self.assertEqual(before, path.read_bytes())
        self.assertEqual({p.name for p in self.root.iterdir()}, {path.name})

    def test_operation_deadline_shared_across_nested_queries(self):
        path, writer = self.make_v3()
        writer.commit()
        writer.close()
        source = SnapshotSource(self.root, 3, deadline_seconds=1)
        self.addCleanup(source.close)
        clock = [100.0]
        with patch('teachmechat.sources.database.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(TeachMeChatError, '时间预算'):
                with source._operation():
                    self.assertEqual(source._select(path, 'SELECT 1'), [(1,)])
                    clock[0] = 100.8
                    self.assertEqual(source._select(path, 'SELECT 2'), [(2,)])
                    clock[0] = 101.1
                    source._select(path, 'SELECT 3')
            # A new operation gets a new budget, not a poisoned connection.
            self.assertEqual(source._select(path, 'SELECT 4'), [(4,)])
        for seconds in (0, -1, float('inf'), float('nan'), True):
            with self.assertRaises(TeachMeChatError):
                SnapshotSource(self.root, 3, deadline_seconds=seconds)

    def test_blob_limits_applied_before_python_fetch(self):
        for version in (3, 4):
            with self.subTest(version=version):
                root = self.root / str(version)
                root.mkdir()
                path = root / ('MSG0.db' if version == 3 else 'message_0.db')
                writer = sqlite3.connect(path)
                if version == 3:
                    writer.execute(V3_SCHEMA)
                    v3_row(writer, 1)
                    v3_row(writer, 2, kind=34)
                    v3_row(writer, 3)
                    writer.execute('UPDATE MSG SET StrContent=zeroblob(?) WHERE localId=1', (MAX_CONTENT + 1,))
                    writer.execute('UPDATE MSG SET BytesExtra=zeroblob(?) WHERE localId=3', (MAX_CONTENT + 1,))
                    writer.execute('CREATE TABLE Media(Reserved0 INTEGER, Buf BLOB)')
                    writer.execute('INSERT INTO Media VALUES(10002, zeroblob(?))', (MAX_VOICE_BYTES + 1,))
                else:
                    table = v4_schema(writer)
                    writer.execute(f'INSERT INTO {table} VALUES(1,10001,1,1,1,100,zeroblob(?),NULL,NULL)', (MAX_CONTENT + 1,))
                    writer.execute(f'INSERT INTO {table} VALUES(2,10002,34,2,1,100,?,NULL,NULL)', ('voice',))
                    writer.execute(f'INSERT INTO {table} VALUES(3,10003,1,3,1,100,?,NULL,zeroblob(?))', ('text', MAX_CONTENT + 1))
                    writer.execute('CREATE TABLE VoiceInfo(svr_id INTEGER, voice_data BLOB)')
                    writer.execute('INSERT INTO VoiceInfo VALUES(10002, zeroblob(?))', (MAX_VOICE_BYTES + 1,))
                writer.commit()
                writer.close()
                source = SnapshotSource(root, version)
                self.addCleanup(source.close)
                real_select = source._select
                fetched = []
                def capture(*args, **kwargs):
                    rows = real_select(*args, **kwargs)
                    if not kwargs.get('columns'):
                        fetched.extend(value for row in rows for value in row)
                    return rows
                with patch.object(source, '_select', side_effect=capture):
                    first, voice, extra = source.recent('friend')
                self.assertEqual(first.text, CONTENT_PLACEHOLDER)
                self.assertTrue(first.metadata['content_omitted'])
                self.assertEqual(extra.text, CONTENT_PLACEHOLDER)
                self.assertEqual(voice.media_bytes, b'')
                self.assertFalse(any(isinstance(value, bytes) and len(value) > MAX_CONTENT for value in fetched))

    def test_voice_size_boundary_and_bounded_transcript(self):
        _, writer = self.make_v3()
        v3_row(writer, 1, kind=34)
        writer.execute('CREATE TABLE Media(Reserved0 INTEGER, Buf BLOB)')
        writer.execute('INSERT INTO Media VALUES(10001, zeroblob(?))', (MAX_VOICE_BYTES,))
        writer.execute('CREATE TABLE Audio2Text(msgSvrId INTEGER, Text TEXT)')
        writer.execute('INSERT INTO Audio2Text VALUES(10001, zeroblob(?))', (MAX_CONTENT + 1,))
        writer.commit()
        writer.close()
        source = SnapshotSource(self.root, 3)
        self.addCleanup(source.close)
        voice = source.recent('friend')[0]
        self.assertEqual(len(voice.media_bytes), MAX_VOICE_BYTES)
        self.assertEqual(voice.text, CONTENT_PLACEHOLDER)

    def test_byte_length_not_text_character_length(self):
        _, writer = self.make_v3()
        v3_row(writer, 1, text='中' * (MAX_CONTENT // 3 + 1))
        writer.commit()
        writer.close()
        source = SnapshotSource(self.root, 3)
        self.addCleanup(source.close)
        self.assertEqual(source.recent('friend')[0].text, CONTENT_PLACEHOLDER)

    def test_scan_known_layout_only_and_never_other_accounts(self):
        allowed = self.root / 'Msg' / 'Multi'
        allowed.mkdir(parents=True)
        (allowed / 'MSG0.db').touch()
        for folder in ('wxid_other/Msg/Multi', 'backup/Msg', '.teachmechat-runtime'):
            directory = self.root / folder
            directory.mkdir(parents=True)
            (directory / 'MSG99.db').touch()
        import os
        scan = os.scandir
        visited = []
        def tracked(path):
            visited.append(Path(path).relative_to(self.root).as_posix())
            return scan(path)
        with patch('teachmechat.sources.database.os.scandir', side_effect=tracked):
            self.assertEqual(database_files(self.root, 3), [(allowed / 'MSG0.db').resolve()])
        self.assertEqual(set(visited), {'.', 'Msg', 'Msg/Multi'})
        with patch('teachmechat.sources.database.MAX_SCAN_ENTRIES', 1):
            with self.assertRaisesRegex(TeachMeChatError, '条目过多'):
                database_files(self.root, 3)
        with patch('teachmechat.sources.database.MAX_DATABASE_FILES', 0):
            with self.assertRaisesRegex(TeachMeChatError, '分片过多'):
                database_files(self.root, 3)
        with self.assertRaisesRegex(TeachMeChatError, '时间预算'):
            database_files(self.root, 3, deadline=monotonic() - 1)

    def test_sqlcipher_v3_v4_uncheckpointed_wal(self):
        try:
            from sqlcipher3 import dbapi2 as cipher
        except ImportError:
            self.skipTest('sqlcipher3 unavailable in existing environment')
        for version in (3, 4):
            with self.subTest(version=version):
                root = self.root / str(version)
                root.mkdir()
                path = root / ('MSG0.db' if version == 3 else 'message_0.db')
                password = bytes(range(32))
                salt = bytes(range(16))
                # Independent expected KDF, not the production derivation helper.
                raw = hashlib.pbkdf2_hmac('sha1' if version == 3 else 'sha512', password, salt,
                                          64000 if version == 3 else 256000, 32)
                self.assertNotEqual(raw, password)
                self.assertEqual(raw, derive_raw_key(password, salt, version))
                writer = cipher.connect(str(path))
                try:
                    writer.execute('PRAGMA key = "x\'' + (raw + salt).hex() + '\'"')
                    writer.execute(f'PRAGMA cipher_compatibility={version}')
                    writer.execute('PRAGMA cipher_page_size=4096')
                    writer.execute(f'PRAGMA kdf_iter={64000 if version == 3 else 256000}')
                    algo = 'SHA1' if version == 3 else 'SHA512'
                    writer.execute(f'PRAGMA cipher_hmac_algorithm=HMAC_{algo}')
                    writer.execute(f'PRAGMA cipher_kdf_algorithm=PBKDF2_HMAC_{algo}')
                    if version == 3:
                        writer.execute(V3_SCHEMA)
                    else:
                        table = v4_schema(writer)
                    writer.commit()
                    writer.execute('PRAGMA journal_mode=WAL')
                    writer.execute('PRAGMA wal_autocheckpoint=0')
                    if version == 3:
                        v3_row(writer, 1, 100)
                    else:
                        writer.execute(f'INSERT INTO {table} VALUES(1,11,1,1,1,100,?,NULL,NULL)', ('synthetic',))
                    writer.commit()
                    self.assertTrue(Path(str(path) + '-wal').stat().st_size > 0)
                    before = {p.name: p.read_bytes() for p in root.iterdir() if not p.name.endswith('-shm')}
                    source = LiveWeChatSource(root, version, password.hex(),
                                              deadline_seconds=10, query_timeout_seconds=0.5)
                    try:
                        with self.assertRaisesRegex(TeachMeChatError, '时间预算'):
                            source._select(path, 'SELECT sum(x) FROM (WITH RECURSIVE work(x) AS '
                                           '(SELECT 1 UNION ALL SELECT x+1 FROM work WHERE x<1000000000) '
                                           'SELECT x FROM work)')
                        self.assertEqual(len(source.recent('friend')), 1)
                        self.assertEqual(source.list_conversations()[0].timestamp, 100)
                        connection = source._connect(path)
                        try:
                            with self.assertRaises(cipher.DatabaseError):
                                connection.execute('CREATE TABLE should_not_exist(x)')
                        finally:
                            connection.close()
                        with ThreadPoolExecutor(max_workers=1) as pool:
                            self.assertEqual(len(pool.submit(source.recent, 'friend').result()), 1)
                    finally:
                        source.close()
                    self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir() if not p.name.endswith('-shm')})
                finally:
                    writer.close()


if __name__ == '__main__':
    unittest.main()
