"""UI-facing source factories. Importing this package never scans accounts."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..models import TeachMeChatError
from .database import LiveWeChatSource, SnapshotSource, database_files


@dataclass(frozen=True)
class AccountInfo:
    root: Path
    version: int
    label: str = ''
    account_id: str = ''


def discover_accounts(roots: Iterable[Path] = (), *, confirmed: bool = False) -> list[AccountInfo]:
    """Inspect filenames ONLY below explicitly supplied, user-confirmed roots.

    This does not discover system account locations, read databases or extract
    keys. The app's separate discovery/key worker owns opt-in automatic access.
    Calling with no arguments is safe and returns [].
    """
    if not confirmed:
        return []
    accounts = []
    seen = set()
    for root in roots:
        root = Path(root).resolve()
        for version in (3, 4):
            if (root, version) not in seen and database_files(root, version):
                seen.add((root, version))
                accounts.append(AccountInfo(root, version, f'微信 V{version} · {root.name}'))
    return accounts


def create_source(root: Path, version: int, *, mode: str = 'snapshot', key: str | None = None,
                  media_root: Path | None = None, account_id: str = '') -> SnapshotSource:
    """Construct after user authorization. Never log or persist the key.

    root accepts an account root, V3 Msg, V4 db_storage, or plaintext export root.
    media_root is an optional independently authorized account media directory.
    account_id is the owner's exact WeChat ID, needed for V4 outgoing detection.
    """
    if mode == 'snapshot':
        source = SnapshotSource(root, version, media_root)
    elif mode == 'live':
        if key is None:
            raise TeachMeChatError('实时读取需要用户授权取得的密钥，或通过隐藏输入手动提供密钥。')
        source = LiveWeChatSource(root, version, key, media_root)
    else:
        raise TeachMeChatError('未知数据源模式，请选择 snapshot 或 live。')
    source.account_id = str(account_id or '')
    return source


__all__ = ['AccountInfo', 'SnapshotSource', 'LiveWeChatSource', 'create_source', 'discover_accounts']
