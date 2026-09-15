"""Exception yang dilempar SDK.

Semua turunan `AlurkerjaError`, jadi script addon cukup menangkap satu kelas
kalau tidak peduli jenis kegagalannya.
"""

from typing import Any, Optional


class AlurkerjaError(Exception):
    """Akar semua error SDK."""


class AlurkerjaConfigError(AlurkerjaError):
    """`svc` tidak lengkap atau tidak sah — gagal sebelum ada request dikirim."""


class AlurkerjaRequestError(AlurkerjaError):
    """Request tidak sampai ke server: DNS, koneksi ditolak, timeout, dsb.

    Membungkus exception `requests` supaya script addon tidak perlu ikut
    mengimpor `requests` hanya untuk menangkap error jaringan.
    """

    def __init__(self, message: str, method: str, url: str) -> None:
        super().__init__(message)
        self.method = method
        self.url = url


class AlurkerjaAPIError(AlurkerjaError):
    """Server menjawab dengan status non-2xx."""

    def __init__(self, status_code: int, body: Any, method: str, url: str) -> None:
        self.status_code = status_code
        self.body = body
        self.method = method
        self.url = url
        super().__init__(f"{method} {url} -> HTTP {status_code}: {_short(body)}")


def _short(body: Optional[Any], limit: int = 500) -> str:
    text = "" if body is None else str(body)
    return text if len(text) <= limit else text[:limit] + "..."
