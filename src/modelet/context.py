"""Login context, the analog of Java's UserInfoHolder.

Uses contextvars instead of ThreadLocal, so it behaves correctly under both
threads and asyncio tasks.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class Login:
    login_id: str


_login: ContextVar[Login | None] = ContextVar("modelet_login", default=None)


def set_login(login: Login | None):
    """Bind the current login; returns a Token usable with ``reset_login``."""
    return _login.set(login)


def get_login() -> Login | None:
    return _login.get()


def reset_login(token) -> None:
    _login.reset(token)
