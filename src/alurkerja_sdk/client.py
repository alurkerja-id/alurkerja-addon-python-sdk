"""Klien HTTP untuk memanggil service AlurKerja dari script addon.

URL dibentuk dari base URL + `/api/v1` + service code + potongan path:

    sdk.post("probis", "masterdata", 1, "customers", "records")
    # -> POST {host}/api/v1/probis/masterdata/1/customers/records
"""

import json as jsonlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Union
from urllib.parse import quote, urlparse

import requests

from .errors import AlurkerjaAPIError, AlurkerjaConfigError, AlurkerjaRequestError

API_PREFIX = "/api/v1"
DEFAULT_TIMEOUT = 30.0

# Service code dipakai langsung sebagai segmen pertama path, jadi dibatasi ke
# bentuk slug seperti di proxy-service (`probis`, `integration`, ...).
_SERVICE_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

PathSegment = Union[str, int]


@dataclass(frozen=True)
class Tenant:
    """Tenant aktif, mengikuti JSON `models.Tenant` di tenant-management-service.

    Field yang tidak dipetakan (`trial_ends_at`, `is_compro_published`, dsb.)
    tetap tersedia lewat `raw`.
    """

    id: Optional[int]
    name: Optional[str]
    slug: Optional[str]
    uuid: Optional[str]
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Tenant":
        return cls(
            id=_to_int(data.get("id")),
            name=data.get("name"),
            slug=data.get("slug"),
            uuid=data.get("uuid"),
            raw=dict(data),
        )


@dataclass(frozen=True)
class Process:
    """BPMN yang sedang menjalankan service task (`svc.process`).

    Identitas definisi (key, version, deployment) diambil platform dari Camunda,
    bukan dari request, jadi aman dipakai untuk logging dan audit.
    """

    definition_id: Optional[str]
    key: Optional[str]
    name: Optional[str]
    version: Optional[int]
    deployment_id: Optional[str]
    tenant_id: Optional[str]
    instance_id: Optional[str]
    business_key: Optional[str]
    activity_id: Optional[str]
    activity_name: Optional[str]
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Process":
        return cls(
            definition_id=data.get("definitionId"),
            key=data.get("key"),
            name=data.get("name"),
            version=_to_int(data.get("version"), "svc.process.version"),
            deployment_id=data.get("deploymentId"),
            tenant_id=data.get("tenantId"),
            instance_id=data.get("instanceId"),
            business_key=data.get("businessKey"),
            activity_id=data.get("activityId"),
            activity_name=data.get("activityName"),
            raw=dict(data),
        )


@dataclass(frozen=True)
class Actor:
    """Pemilik token (`svc.actor`). `source` saat ini selalu `deployer`."""

    email: Optional[str]
    source: Optional[str]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Actor":
        return cls(email=data.get("email"), source=data.get("source"))


def _to_int(value: Any, name: str = "svc.tenant.id") -> Optional[int]:
    # id tenant di model berupa uint; config dari form bisa mengirimnya sebagai "1".
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise AlurkerjaConfigError(f"{name} harus angka: {value!r}") from None


class AlurkerjaSDK:
    """Klien untuk service AlurKerja.

    Args:
        svc: Informasi service dari platform. Wajib berisi `token` dan
            `baseurl`; `tenant` ({id, name, slug, uuid}), `process`, dan `actor`
            opsional. Key lain tetap bisa dibaca lewat `sdk.svc`. Boleh juga
            berupa string JSON.
        timeout: Batas waktu request dalam detik.
        session: `requests.Session` sendiri, mis. untuk test atau pooling.
    """

    def __init__(
        self,
        svc: Union[Mapping[str, Any], str],
        *,
        timeout: float = DEFAULT_TIMEOUT,
        session: Optional[requests.Session] = None,
    ) -> None:
        svc = _load_svc(svc)

        token = svc.get("token")
        if not isinstance(token, str) or not token.strip():
            raise AlurkerjaConfigError("svc.token wajib diisi")

        self.svc: Dict[str, Any] = dict(svc)
        self.api_url = _normalize_base_url(svc.get("baseurl"))
        self.timeout = timeout

        tenant = svc.get("tenant")
        if tenant is not None and not isinstance(tenant, Mapping):
            raise AlurkerjaConfigError("svc.tenant harus berupa object {id, name, slug, uuid}")
        self.tenant: Optional[Tenant] = Tenant.from_mapping(tenant) if tenant else None
        self.process: Optional[Process] = _optional_section(svc, "process", Process.from_mapping)
        self.actor: Optional[Actor] = _optional_section(svc, "actor", Actor.from_mapping)

        token = token.strip()
        self._auth_header = token if token.lower().startswith("bearer ") else f"Bearer {token}"
        self._session = session or requests.Session()

    @classmethod
    def from_ctx(cls, ctx: Mapping[str, Any], **kwargs: Any) -> "AlurkerjaSDK":
        """Buat SDK dari execution context script addon.

        Mencari `ctx["svc"]` lebih dulu, lalu `ctx["configuration"]["svc"]`.
        """
        svc = ctx.get("svc")
        if svc is None:
            configuration = ctx.get("configuration") or {}
            svc = configuration.get("svc") if isinstance(configuration, Mapping) else None
        if svc is None:
            raise AlurkerjaConfigError("svc tidak ditemukan di ctx['svc'] maupun ctx['configuration']['svc']")
        return cls(svc, **kwargs)

    def __repr__(self) -> str:
        tenant = self.tenant.slug if self.tenant else None
        return f"AlurkerjaSDK(api_url={self.api_url!r}, tenant={tenant!r}, token='***')"

    def get(self, service: str, *path: PathSegment, **kwargs: Any) -> Any:
        return self.request("GET", service, *path, **kwargs)

    def post(self, service: str, *path: PathSegment, **kwargs: Any) -> Any:
        return self.request("POST", service, *path, **kwargs)

    def put(self, service: str, *path: PathSegment, **kwargs: Any) -> Any:
        return self.request("PUT", service, *path, **kwargs)

    def patch(self, service: str, *path: PathSegment, **kwargs: Any) -> Any:
        return self.request("PATCH", service, *path, **kwargs)

    def delete(self, service: str, *path: PathSegment, **kwargs: Any) -> Any:
        return self.request("DELETE", service, *path, **kwargs)

    def build_url(self, service: str, *path: PathSegment) -> str:
        """URL lengkap tanpa query string, untuk logging atau debugging."""
        if not isinstance(service, str) or not _SERVICE_CODE.match(service):
            raise ValueError(f"service code tidak sah: {service!r}")
        segments = [service] + [_encode_segment(segment) for segment in path]
        return f"{self.api_url}/{'/'.join(segments)}"

    def request(
        self,
        method: str,
        service: str,
        *path: PathSegment,
        params: Optional[Mapping[str, Any]] = None,
        json: Any = None,
        data: Any = None,
        files: Any = None,
        headers: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """Kirim request dan kembalikan body yang sudah diurai.

        Returns:
            JSON yang sudah di-parse, teks untuk `text/*`, bytes untuk konten
            lain (mis. unduhan file), atau `None` kalau body kosong.

        Raises:
            AlurkerjaAPIError: server menjawab non-2xx.
            AlurkerjaRequestError: request gagal terkirim.
        """
        method = method.upper()
        url = self.build_url(service, *path)

        request_headers = {"Authorization": self._auth_header, "Accept": "application/json"}
        if self.tenant and self.tenant.slug:
            # bpm-service membaca slug tenant aktif dari header ini.
            request_headers["x-active-tenant"] = str(self.tenant.slug)
        if headers:
            request_headers.update(headers)

        try:
            response = self._session.request(
                method,
                url,
                params=_encode_params(params),
                json=json,
                data=data,
                files=files,
                headers=request_headers,
                timeout=self.timeout if timeout is None else timeout,
            )
        except requests.RequestException as exc:
            raise AlurkerjaRequestError(f"{method} {url} gagal: {exc}", method, url) from exc

        body = _decode_body(response)
        if not 200 <= response.status_code < 300:
            raise AlurkerjaAPIError(response.status_code, body, method, url)
        return body


def _optional_section(svc: Mapping[str, Any], key: str, build: Any) -> Any:
    section = svc.get(key)
    if section is None:
        return None
    if not isinstance(section, Mapping):
        raise AlurkerjaConfigError(f"svc.{key} harus berupa object")
    return build(section)


def _load_svc(svc: Union[Mapping[str, Any], str]) -> Mapping[str, Any]:
    # Nilai config dari form setting addon bisa tersimpan sebagai string JSON.
    if isinstance(svc, str):
        try:
            svc = jsonlib.loads(svc)
        except ValueError as exc:
            raise AlurkerjaConfigError(f"svc bukan JSON yang sah: {exc}") from exc
    if not isinstance(svc, Mapping):
        raise AlurkerjaConfigError("svc harus berupa object")
    return svc


def _normalize_base_url(baseurl: Any) -> str:
    """Terima `http://host`, `http://host/api/v1`, maupun dengan slash di akhir."""
    if not isinstance(baseurl, str) or not baseurl.strip():
        raise AlurkerjaConfigError("svc.baseurl wajib diisi")

    url = baseurl.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise AlurkerjaConfigError(f"svc.baseurl harus URL http/https: {baseurl!r}")

    if url.lower().endswith(API_PREFIX):
        url = url[: -len(API_PREFIX)]
    return url + API_PREFIX


def _encode_segment(segment: PathSegment) -> str:
    # bool turunan int, jadi `True` akan lolos jadi "True" kalau tidak ditolak.
    if isinstance(segment, bool) or not isinstance(segment, (str, int)):
        raise ValueError(f"segmen path harus str atau int: {segment!r}")

    text = str(segment)
    # Segmen sering berasal dari `parameters` user; "/" dan ".." bisa
    # membelokkan request ke endpoint lain, jadi ditolak, bukan di-encode.
    if text in ("", ".", "..") or "/" in text or "\\" in text:
        raise ValueError(f"segmen path tidak sah: {segment!r}")
    return quote(text, safe="")


def _encode_params(params: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """`None` dibuang, bool jadi `true`/`false`, list dikirim berulang."""
    if params is None:
        return None

    encoded: Dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            encoded[key] = [_encode_param_value(item) for item in value if item is not None]
        else:
            encoded[key] = _encode_param_value(value)
    return encoded


def _encode_param_value(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _decode_body(response: requests.Response) -> Any:
    if not response.content:
        return None

    content_type = response.headers.get("Content-Type", "").lower()
    if "json" in content_type:
        try:
            return response.json()
        except ValueError:
            return response.text
    if content_type.startswith("text/") or not content_type:
        return response.text
    return response.content
