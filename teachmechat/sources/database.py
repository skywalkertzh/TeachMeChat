"""Read-only adapters for explicitly selected WeChat V3/V4 databases.

No wxManager imports, logging, decryption exports, schema changes, or checkpoints.
Each SELECT owns a short-lived connection, so UI and reader threads may share a
source. A live WAL uses normal SQLite locking (never immutable=1).
"""
from __future__ import annotations

import hashlib
import importlib
import math
import os
import re
import sqlite3
import stat
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from pathlib import Path
from threading import RLock, local
from time import monotonic

from ..models import ChatMessage, Conversation, TeachMeChatError
from .parsing import MAX_CONTENT, decode_content, parse_media, safe_media_path, v3_extra, v4_packed

_PATTERNS = {
    3: re.compile(r'(?:MSG\d*|MicroMsg|MediaMSG\d*|Audio2Text|HardLinkImage)\.db$', re.I),
    4: re.compile(r'(?:message_\d+|contact|media_\d+|session|hardlink|Audio2Text)\.db$', re.I),
}


MAX_VOICE_BYTES = 25 * 1024 * 1024
MAX_DATABASE_FILES = 256
MAX_SCAN_ENTRIES = 4096
MAX_SCHEMA_TABLES = 4096
CONTENT_PLACEHOLDER = '[消息内容超过安全大小限制，已省略]'
_TIMEOUT_MESSAGE = '只读读取超过时间预算，已取消；请缩小查询范围后重试。'
# Only known layouts within ONE explicitly selected account/export root.
# Never recursively descend into sibling accounts, backups, media or runtime.
_LAYOUTS = {
    3: ('', 'Multi', 'Msg', 'Msg/Multi'),
    4: ('', 'message', 'contact', 'media', 'session', 'hardlink',
        'db_storage', 'db_storage/message', 'db_storage/contact',
        'db_storage/media', 'db_storage/session', 'db_storage/hardlink'),
}


def _seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise TeachMeChatError('读取时间预算必须是有限的正数。')
    return float(value)


def _check_deadline(deadline):
    if monotonic() >= deadline:
        raise TeachMeChatError(_TIMEOUT_MESSAGE)


def _is_link(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400))


def database_files(root: Path, version: int, *, deadline=None) -> list[Path]:
    if version not in (3, 4):
        raise TeachMeChatError('仅支持微信数据库 V3 / V4。')
    deadline = monotonic() + 10.0 if deadline is None else deadline
    _check_deadline(deadline)
    root = Path(root).resolve()
    if not root.is_dir():
        raise TeachMeChatError('请选择已授权且存在的数据库目录。')
    files = set()
    entries = 0
    try:
        for layout in _LAYOUTS[version]:
            _check_deadline(deadline)
            directory = root / layout
            parts = Path(layout).parts
            if any(_is_link(root.joinpath(*parts[:i])) for i in range(1, len(parts) + 1)
                   if root.joinpath(*parts[:i]).exists()):
                continue
            if not directory.is_dir():
                continue
            with os.scandir(directory) as children:
                for entry in children:
                    _check_deadline(deadline)
                    entries += 1
                    if entries > MAX_SCAN_ENTRIES:
                        raise TeachMeChatError('数据库目录条目过多，请选择单个账号的数据库目录。')
                    if not _PATTERNS[version].fullmatch(entry.name):
                        continue
                    path = Path(entry.path)
                    if entry.is_file(follow_symlinks=False) and not _is_link(path):
                        resolved = path.resolve()
                        if resolved.is_relative_to(root):
                            files.add(resolved)
                            if len(files) > MAX_DATABASE_FILES:
                                raise TeachMeChatError('数据库分片过多，请缩小读取范围。')
    except OSError:
        raise TeachMeChatError('无法只读扫描所选数据库目录。') from None
    _check_deadline(deadline)
    return sorted(files, key=lambda p: p.as_posix().casefold())


def _bounded_operation(method):
    @wraps(method)
    def bounded(self, *args, **kwargs):
        with self._operation():
            return method(self, *args, **kwargs)
    return bounded


def _bounded_column(name, fallback='NULL'):
    column = quote_identifier(name)
    # Cast TEXT to BLOB so the limit is in bytes, including embedded NULs.
    return f'CASE WHEN length(CAST({column} AS BLOB)) <= {MAX_CONTENT} THEN {column} ELSE {fallback} END'


def quote_identifier(name: str) -> str:
    if not isinstance(name, str) or '\x00' in name:
        raise TeachMeChatError('数据库标识符无效。')
    return '"' + name.replace('"', '""') + '"'


def derive_raw_key(password: bytes, salt: bytes, version: int) -> bytes:
    """WeChat's 32 password bytes are NOT a SQLCipher raw encryption key."""
    if version not in (3, 4) or len(password) != 32 or len(salt) != 16:
        raise TeachMeChatError('数据库版本或密钥格式无效。')
    return hashlib.pbkdf2_hmac('sha1' if version == 3 else 'sha512', password,
                               salt, 64000 if version == 3 else 256000, 32)


def _sqlcipher_driver():
    for name in ('sqlcipher3.dbapi2', 'pysqlcipher3.dbapi2'):
        try:
            return importlib.import_module(name)
        except (ImportError, OSError):
            continue
    raise TeachMeChatError('实时读取需要 SQLCipher（优先 sqlcipher3）；不会回退为明文或导出数据库。')


def _read_authorizer(action, arg1, arg2, db, trigger):
    # A second guard in addition to mode=ro, query_only and SELECT-only calls.
    return sqlite3.SQLITE_OK if action in (
        sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
        getattr(sqlite3, 'SQLITE_RECURSIVE', 33),
    ) else sqlite3.SQLITE_DENY


class SnapshotSource:
    status_label = '明文快照 · 只读'

    def __init__(self, root: Path, version: int, media_root: Path | None = None, *,
                 deadline_seconds: float = 10.0, query_timeout_seconds: float = 3.0):
        if version not in (3, 4):
            raise TeachMeChatError('仅支持微信数据库 V3 / V4。')
        self.deadline_seconds = _seconds(deadline_seconds)
        self.query_timeout_seconds = _seconds(query_timeout_seconds)
        self._budget = local()
        self.root = Path(root).resolve()
        self.version = version
        self.media_root = Path(media_root).resolve() if media_root is not None else None
        self.account_id = ''  # Set explicitly by create_source; never infer from private info.json.
        self._closed = False
        self._lock = RLock()
        self._driver = getattr(self, '_driver', sqlite3)
        self._schema_cache = {}
        with self._operation():
            self._files = database_files(self.root, version, deadline=self._budget.deadline)
            if not self._files:
                raise TeachMeChatError('目录中没有对应版本的受支持数据库文件。')
            # Validate now rather than silently producing an empty chat list.
            if not any(self._message_tables(path, self._schema(path)) for path in self._files):
                raise TeachMeChatError('没有找到对应版本的消息表，请核对数据库目录和版本。')

    @contextmanager
    def _operation(self):
        previous = getattr(self._budget, 'deadline', None)
        if previous is None:
            self._budget.deadline = monotonic() + self.deadline_seconds
        try:
            _check_deadline(self._budget.deadline)
            yield
            _check_deadline(self._budget.deadline)
        finally:
            if previous is None:
                del self._budget.deadline

    def _configure(self, connection, path: Path):
        pass

    def _connect(self, path: Path, *, deadline=None):
        connection = None
        try:
            wal = Path(str(path) + '-wal')
            shm = Path(str(path) + '-shm')
            if wal.is_file() and wal.stat().st_size and not shm.is_file():
                raise TeachMeChatError('检测到 WAL 但缺少 SHM；为避免创建或改动源文件，请由数据库所属应用恢复 SHM 后重试。')
            # URI encoding protects ?, # and quotes in user-supplied paths.
            deadline = deadline if deadline is not None else monotonic() + self.query_timeout_seconds
            _check_deadline(deadline)
            connection = self._driver.connect(path.as_uri() + '?mode=ro', uri=True,
                                              timeout=max(0.0, min(2.0, deadline - monotonic())),
                                              isolation_level=None)
            connection.set_progress_handler(lambda: int(monotonic() >= deadline), 1000)
            self._configure(connection, path)
            connection.execute('PRAGMA query_only=ON')
            connection.execute('PRAGMA temp_store=MEMORY')
            connection.execute('PRAGMA trusted_schema=OFF')
            connection.set_authorizer(_read_authorizer)
            _check_deadline(deadline)
            return connection
        except TeachMeChatError:
            if connection is not None:
                connection.close()
            raise
        except Exception:
            if connection is not None:
                connection.close()
            if deadline is not None and monotonic() >= deadline:
                raise TeachMeChatError(_TIMEOUT_MESSAGE) from None
            raise TeachMeChatError('只读数据库连接失败；请核对版本、密钥、访问权限及 WAL/SHM 可读性。') from None

    @_bounded_operation
    def _select(self, path: Path, sql: str, parameters=(), *, columns=False):
        if self._closed:
            raise TeachMeChatError('数据源已关闭。')
        if not sql.lstrip().upper().startswith('SELECT '):
            raise TeachMeChatError('数据源仅允许明确的 SELECT 查询。')
        deadline = min(self._budget.deadline, monotonic() + self.query_timeout_seconds)
        connection = None
        try:
            _check_deadline(deadline)
            connection = self._connect(path, deadline=deadline)
            # This bounds execute AND fetch, not merely SQLite's busy wait.
            connection.set_progress_handler(lambda: int(monotonic() >= deadline), 1000)
            cursor = connection.execute(sql, parameters)
            result = [item[0] for item in cursor.description] if columns else cursor.fetchall()
            cursor.close()  # finishes SQLite's implicit read transaction
            _check_deadline(deadline)
            return result
        except TeachMeChatError:
            raise
        except Exception:
            if monotonic() >= deadline:
                raise TeachMeChatError(_TIMEOUT_MESSAGE) from None
            raise TeachMeChatError('只读查询失败；数据库可能忙碌、版本不匹配、密钥错误或数据损坏。') from None
        finally:
            if connection is not None:
                connection.close()

    @_bounded_operation
    def _schema(self, path: Path):
        with self._lock:
            _check_deadline(self._budget.deadline)
            if path not in self._schema_cache:
                tables = self._select(path, f"SELECT name FROM sqlite_master WHERE type='table' LIMIT {MAX_SCHEMA_TABLES + 1}")
                if len(tables) > MAX_SCHEMA_TABLES:
                    raise TeachMeChatError('数据库消息表过多，请缩小读取范围。')
                self._schema_cache[path] = {
                    name: {col.lower(): col for col in self._select(
                        path, f'SELECT * FROM {quote_identifier(name)} LIMIT 0', columns=True)}
                    for (name,) in tables
                }
            return self._schema_cache[path]

    @_bounded_operation
    def _refresh(self):
        if self._closed:
            raise TeachMeChatError('数据源已关闭。')
        # Live rotation may introduce new shards or conversation tables.
        with self._lock:
            self._files = database_files(self.root, self.version, deadline=self._budget.deadline)
            self._schema_cache.clear()
            return tuple(self._files)

    def _message_tables(self, path, schema):
        if self.version == 3:
            return [name for name, cols in schema.items() if name.lower() == 'msg'
                    and {'strtalker', 'createtime', 'localid', 'strcontent'} <= cols.keys()]
        return [name for name, cols in schema.items() if re.fullmatch(r'Msg_[0-9a-fA-F]{32}', name)
                and {'local_id', 'create_time', 'sort_seq', 'message_content'} <= cols.keys()]

    @staticmethod
    def _table(schema, name):
        return next((table for table in schema if table.lower() == name.lower()), None)

    def _contacts(self, files):
        contacts = {}
        aliases = {}
        for path in files:
            schema = self._schema(path)
            table = self._table(schema, 'Contact')
            if not table:
                continue
            cols = schema[table]
            username = 'username'
            nick = 'nickname' if self.version == 3 else 'nick_name'
            if username not in cols:
                continue
            expressions = [quote_identifier(cols[c]) if c in cols else "''"
                           for c in (username, 'remark', nick, 'alias')]
            for user, remark, nickname, alias in self._select(path,
                    f'SELECT {", ".join(expressions)} FROM {quote_identifier(table)}'):
                if user:
                    contacts[str(user)] = str(remark or nickname or user)
                    aliases[str(user)] = str(alias or '')
        return contacts, aliases

    def _v4_names(self, files):
        names = {}
        for path in files:
            schema = self._schema(path)
            table = self._table(schema, 'Name2Id')
            if table and 'user_name' in schema[table]:
                for (name,) in self._select(path, f'SELECT user_name FROM {quote_identifier(table)}'):
                    if name:
                        names[hashlib.md5(str(name).encode()).hexdigest()] = str(name)
        return names

    @_bounded_operation
    def list_conversations(self) -> list[Conversation]:
        files = self._refresh()
        contacts, _ = self._contacts(files)
        names = self._v4_names(files) if self.version == 4 else {}
        for user in contacts:
            names[hashlib.md5(user.encode()).hexdigest()] = user
        timestamps = {}
        for path in files:
            schema = self._schema(path)
            for table in self._message_tables(path, schema):
                quoted = quote_identifier(table)
                if self.version == 3:
                    rows = self._select(path, f'SELECT StrTalker, MAX(CreateTime) FROM {quoted} GROUP BY StrTalker')
                else:
                    user = names.get(table[4:].lower(), table)
                    rows = [(user, self._select(path, f'SELECT MAX(create_time) FROM {quoted}')[0][0])]
                for user, timestamp in rows:
                    if user and timestamp is not None:
                        timestamps[user] = max(timestamps.get(user, 0), int(timestamp))
        return [Conversation(user, contacts.get(user, user), timestamp) for user, timestamp in
                sorted(timestamps.items(), key=lambda item: (-item[1], item[0]))]

    @_bounded_operation
    def search_contacts(self, query: str, limit: int = 100) -> list[Conversation]:
        if limit <= 0:
            return []
        files = self._refresh()
        contacts, aliases = self._contacts(files)
        recent = {item.id: item for item in self.list_conversations()}
        for user, name in contacts.items():
            recent.setdefault(user, Conversation(user, name))
        needle = query.casefold().strip()
        matches = [item for item in recent.values() if any(needle in value.casefold()
                   for value in (item.id, item.name, aliases.get(item.id, '')))]
        return sorted(matches, key=lambda item: (-item.timestamp, item.name, item.id))[:limit]

    @_bounded_operation
    def recent(self, conversation_id: str, limit: int = 100) -> list[ChatMessage]:
        """Latest N, oldest first. Stable tie key includes sequence/local ID/shard.

        No timestamp-only paging: each shard supplies its own top N, then the
        merged result is truncated. Same-second messages are never skipped.
        """
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise TeachMeChatError('消息数量必须是非负整数。')
        if limit == 0:
            return []
        files = self._refresh()
        expected = 'Msg_' + hashlib.md5(conversation_id.encode()).hexdigest()
        # An unresolved hash-table ID from list_conversations can still be opened.
        if re.fullmatch(r'Msg_[0-9a-fA-F]{32}', conversation_id):
            expected = conversation_id
        candidates = []
        for path in files:
            schema = self._schema(path)
            for table in self._message_tables(path, schema):
                if self.version == 4 and table.lower() != expected.lower():
                    continue
                cols = schema[table]
                wanted = (('localid', 'createtime', 'type', 'issender', 'strcontent', 'compresscontent',
                           'msgsvrid', 'bytesextra', 'displaycontent') if self.version == 3 else
                          ('local_id', 'create_time', 'local_type', 'sort_seq', 'message_content',
                           'compress_content', 'server_id', 'real_sender_id', 'packed_info_data'))
                payloads = {'strcontent', 'compresscontent', 'bytesextra', 'displaycontent',
                            'message_content', 'compress_content', 'packed_info_data'}
                expressions = [(_bounded_column(cols[col]) if col in payloads else quote_identifier(cols[col]))
                               if col in cols else 'NULL' for col in wanted]
                oversized = ' OR '.join(f'length(CAST({quote_identifier(cols[col])} AS BLOB)) > {MAX_CONTENT}'
                                        for col in wanted if col in cols and col in payloads) or '0'
                expressions.append(f'CASE WHEN {oversized} THEN 1 ELSE 0 END')
                if self.version == 3:
                    suffix = 'WHERE StrTalker=? ORDER BY CreateTime DESC, localId DESC, rowid DESC LIMIT ?'
                    params = (conversation_id, limit)
                else:
                    suffix = 'ORDER BY create_time DESC, sort_seq DESC, local_id DESC, rowid DESC LIMIT ?'
                    params = (limit,)
                rows = self._select(path, f'SELECT rowid, {", ".join(expressions)} FROM {quote_identifier(table)} {suffix}', params)
                senders = {}
                names_table = self._table(schema, 'Name2Id')
                if self.version == 4 and rows and names_table:
                    senders = dict(self._select(path, f'SELECT rowid, user_name FROM {quote_identifier(names_table)}'))
                shard = path.relative_to(self.root).as_posix()
                for row in rows:
                    record = dict(zip(wanted, row[1:]))
                    record['_content_omitted'] = bool(row[-1])
                    timestamp = int(record.get('createtime', record.get('create_time')) or 0)
                    local_id = int(record.get('localid', record.get('local_id')) or 0)
                    sequence = int(record.get('sort_seq') or local_id)
                    tie = (timestamp, sequence, local_id, shard, int(row[0]))
                    candidates.append((tie, record, senders, shard, int(row[0])))
        selected = sorted(candidates, key=lambda item: item[0])[-limit:]
        result = []
        for tie, record, senders, shard, rowid in selected:
            _check_deadline(self._budget.deadline)
            content = record.get('strcontent', record.get('message_content'))
            compressed = record.get('compresscontent', record.get('compress_content'))
            text = CONTENT_PLACEHOLDER if record['_content_omitted'] else decode_content(content, compressed, self.version)
            msg_type = int(record.get('type', record.get('local_type')) or 1) & 0xffffffff
            kind = {1: 'text', 3: 'image', 34: 'voice'}.get(msg_type, 'other')
            sender = (self.account_id or '我') if record.get('issender') else conversation_id
            outgoing = bool(record.get('issender'))
            if self.version == 4:
                sender = str(senders.get(record.get('real_sender_id'), conversation_id))
                outgoing = bool(self.account_id and sender == self.account_id)
            extra = record.get('bytesextra')
            if conversation_id.endswith('@chatroom') and not outgoing:
                prefix, separator, rest = text.partition(':\n')
                if separator:
                    sender, text = prefix, rest
                elif self.version == 3:
                    sender = v3_extra(extra).get(1, sender)
            media_path, metadata = parse_media(text, kind, self.media_root, extra)
            packed = v4_packed(record.get('packed_info_data')) if self.version == 4 else {}
            if packed.get('wechat_transcript'):
                metadata.setdefault('wechat_transcript', packed['wechat_transcript'])
            server_id = record.get('msgsvrid', record.get('server_id'))
            metadata.update({'server_id': str(server_id or ''), 'local_id': tie[2],
                             'sort_seq': tie[1], 'source_shard': shard})
            if self.version == 4 and not self.account_id:
                metadata['outgoing_unknown'] = True
            if kind == 'voice':
                data, transcript = self._voice(files, server_id)
                if transcript:
                    metadata['wechat_transcript'] = transcript
                display = record.get('displaycontent')
                if display and not metadata.get('wechat_transcript'):
                    _, display_metadata = parse_media(str(display), kind, self.media_root)
                    metadata.update(display_metadata)
                text = metadata.get('wechat_transcript') or '[语音]'
            else:
                data = b''
            if kind == 'image':
                if self.version == 4 and self.media_root:
                    month = datetime.fromtimestamp(tie[0]).strftime('%Y-%m')
                    directory = f'msg/attach/{hashlib.md5(conversation_id.encode()).hexdigest()}/{month}/Img'
                    basename = packed.get('filename') or f'{tie[2]}_{tie[0]}'
                    for suffix in ('_W.dat', '_h.dat', '.dat'):
                        media_path = media_path or safe_media_path(self.media_root, f'{directory}/{basename}{suffix}')
                    thumbnail = safe_media_path(self.media_root, f'{directory}/{basename}_t.dat')
                    if thumbnail:
                        metadata.setdefault('thumbnail_path', thumbnail)
                text = '[图片]'
            if record['_content_omitted']:
                metadata['content_omitted'] = True
                text = CONTENT_PLACEHOLDER
            result.append(ChatMessage(
                id=f'v{self.version}:{shard}:{conversation_id}:{tie[2]}:{rowid}',
                timestamp=tie[0], sender=sender, text=text, kind=kind, outgoing=outgoing,
                media_path=media_path, media_bytes=data, metadata=metadata))
        return result

    @_bounded_operation
    def _voice(self, files, server_id):
        if not server_id:
            return b'', ''
        data, transcript = b'', ''
        for path in files:
            schema = self._schema(path)
            table = self._table(schema, 'Media' if self.version == 3 else 'VoiceInfo')
            if table and not data:
                column, key = ('Buf', 'Reserved0') if self.version == 3 else ('voice_data', 'svr_id')
                if {column.lower(), key.lower()} <= schema[table].keys():
                    quoted = quote_identifier(column)
                    rows = self._select(path, f'SELECT {quoted} FROM {quote_identifier(table)} '
                                        f'WHERE {quote_identifier(key)}=? AND typeof({quoted})=\'blob\' '
                                        f'AND length({quoted}) <= ? LIMIT 1', (server_id, MAX_VOICE_BYTES))
                    if rows and isinstance(rows[0][0], bytes):
                        data = rows[0][0]
            table = self._table(schema, 'Audio2Text')
            if table and {'text', 'msgsvrid'} <= schema[table].keys() and not transcript:
                expression = _bounded_column('Text', "'" + CONTENT_PLACEHOLDER + "'")
                rows = self._select(path, f'SELECT {expression} FROM {quote_identifier(table)} WHERE msgSvrId=? LIMIT 1', (server_id,))
                if rows:
                    transcript = str(rows[0][0] or '')
        return data, transcript

    def close(self):
        with self._lock:
            self._closed = True
            self._schema_cache.clear()


class LiveWeChatSource(SnapshotSource):
    status_label = '微信实时数据库 · SQLCipher 只读'

    def __init__(self, root: Path, version: int, key: str, media_root: Path | None = None, *,
                 deadline_seconds: float = 10.0, query_timeout_seconds: float = 3.0):
        if version not in (3, 4):
            raise TeachMeChatError('仅支持微信数据库 V3 / V4。')
        if not isinstance(key, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', key.strip()):
            raise TeachMeChatError('微信密钥须为 64 位十六进制字符（32 字节）。')
        self._password = bytearray.fromhex(key.strip())
        self._derived = {}
        try:
            self._driver = _sqlcipher_driver()
            super().__init__(root, version, media_root, deadline_seconds=deadline_seconds,
                             query_timeout_seconds=query_timeout_seconds)
        except Exception:
            self._password[:] = b'\x00' * len(self._password)
            self._derived.clear()
            raise

    def _configure(self, connection, path: Path):
        cipher_version = connection.execute('PRAGMA cipher_version').fetchone()
        if not cipher_version or not cipher_version[0]:
            raise TeachMeChatError('当前驱动未启用 SQLCipher，不能读取实时加密数据库。')
        major = int(str(cipher_version[0]).split('.')[0])
        if self.version == 4 and major < 4:
            raise TeachMeChatError('V4 数据库需要 SQLCipher 4 或更高版本。')
        with path.open('rb') as handle:
            salt = handle.read(16)
        if salt == b'SQLite format 3\x00':
            raise TeachMeChatError('实时源要求加密数据库；明文数据库请使用快照模式。')
        with self._lock:
            if salt not in self._derived:
                self._derived[salt] = derive_raw_key(bytes(self._password), salt, self.version)
            raw = self._derived[salt]
        # Supplying key+salt bypasses the passphrase KDF only after we have
        # applied WeChat's byte-password KDF ourselves, once per file salt.
        connection.execute('PRAGMA key = "x\'' + (raw + salt).hex() + '\'"')
        connection.execute(f'PRAGMA cipher_compatibility={self.version}')
        connection.execute('PRAGMA cipher_page_size=4096')
        connection.execute(f'PRAGMA kdf_iter={64000 if self.version == 3 else 256000}')
        algorithm = 'SHA1' if self.version == 3 else 'SHA512'
        connection.execute(f'PRAGMA cipher_hmac_algorithm=HMAC_{algorithm}')
        connection.execute(f'PRAGMA cipher_kdf_algorithm=PBKDF2_HMAC_{algorithm}')
        connection.execute('PRAGMA cipher_use_hmac=ON')
        # No checkpoint, rekey, migrate, journal_mode change or immutable URI.

    def close(self):
        super().close()
        with self._lock:
            self._password[:] = b'\x00' * len(self._password)
            self._derived.clear()
