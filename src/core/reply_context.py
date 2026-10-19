"""一条命令正在处理时，把回复改发到私信。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_private_reply_uid: ContextVar[str] = ContextVar("private_reply_uid", default="")


def current_private_reply_uid() -> str:
    return _private_reply_uid.get()


@contextmanager
def use_private_reply(uid: str):
    token = _private_reply_uid.set(str(uid or "").strip())
    try:
        yield
    finally:
        _private_reply_uid.reset(token)
