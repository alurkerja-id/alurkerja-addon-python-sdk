# alurkerja-sdk

SDK Python untuk script addon AlurKerja. Script cukup menerima `svc` dari
platform, lalu memanggil service AlurKerja (mis. master data di `probis`) tanpa
merakit URL, header auth, atau header tenant sendiri.

## Instalasi

```bash
pip install "git+https://github.com/alurkerja-id/alurkerja-addon-python-sdk.git@v0.1.0"
```

Lewat SSH:

```bash
pip install "git+ssh://git@github.com/alurkerja-id/alurkerja-addon-python-sdk.git@v0.1.0"
```

Di `requirements.txt`:

```text
alurkerja-sdk @ git+https://github.com/alurkerja-id/alurkerja-addon-python-sdk.git@v0.1.0
```

## Pemakaian

```python
from alurkerja_sdk import AlurkerjaSDK, AlurkerjaAPIError


def run(ctx):
    sdk = AlurkerjaSDK.from_ctx(ctx)          # atau AlurkerjaSDK(ctx["configuration"]["svc"])

    # GET /api/v1/probis/masterdata/1/customers/records?page=1
    records = sdk.get(
        "probis", "masterdata", sdk.tenant.id, "customers", "records",
        params={"page": 1},
    )

    # POST /api/v1/probis/masterdata/1/customers/records?upsert=true
    try:
        created = sdk.post(
            "probis", "masterdata", sdk.tenant.id, "customers", "records",
            params={"upsert": True},
            json={"name": "PT A"},
        )
    except AlurkerjaAPIError as err:
        return {"status": err.status_code, "data": err.body}

    return {"status": "ok", "data": {"records": records, "created": created}}
```

### `svc`

```json
{
  "token": "eyJ...",
  "baseurl": "http://asdb.com/api/v1",
  "tenant": {
    "id": 1,
    "name": "Tenant A",
    "slug": "tenant-a",
    "uuid": "f8672713-7ec0-4a8a-98ba-f6adf420d105"
  }
}
```

| Key | Wajib | Keterangan |
|---|---|---|
| `token` | ya | Dikirim sebagai `Authorization: Bearer <token>`. Prefix `Bearer ` boleh ada atau tidak. |
| `baseurl` | ya | `http://host`, `http://host/api/v1`, dan slash di akhir semuanya dianggap sama. |
| `tenant` | tidak | Mengikuti JSON `models.Tenant` di tenant-management-service. Dibaca sebagai `sdk.tenant.id/.name/.slug/.uuid`; field lain lewat `sdk.tenant.raw`. Kalau ada `slug`, dikirim sebagai header `x-active-tenant`. |
| lainnya | tidak | Tetap bisa dibaca lewat `sdk.svc["..."]`. |

`svc` juga boleh berupa string JSON. `from_ctx` mencari `ctx["svc"]` lebih dulu,
lalu `ctx["configuration"]["svc"]`.

### Method

`get`, `post`, `put`, `patch`, `delete`, dan `request(method, ...)`, semuanya
dengan bentuk `(service, *path, params=, json=, data=, files=, headers=, timeout=)`.

- **URL**: `{baseurl}/api/v1/{service}/{path...}`. Tiap segmen di-URL-encode;
  segmen kosong, `.`, `..`, atau yang mengandung `/` ditolak dengan `ValueError`.
- **`params`**: nilai `None` dibuang, `True`/`False` dikirim sebagai `true`/`false`,
  list dikirim berulang (`{"id": [1, 2]}` → `?id=1&id=2`).
- **Hasil**: JSON yang sudah di-parse, `str` untuk `text/*`, `bytes` untuk konten
  lain (mis. unduhan file), atau `None` kalau body kosong.

### Error

| Exception | Kapan |
|---|---|
| `AlurkerjaConfigError` | `svc` tidak lengkap/tidak sah, sebelum request dikirim. |
| `AlurkerjaRequestError` | Request tidak sampai ke server (koneksi, DNS, timeout). |
| `AlurkerjaAPIError` | Server menjawab non-2xx. Punya `status_code`, `body`, `method`, `url`. |

Semuanya turunan `AlurkerjaError`.

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
python -m build          # hasil di dist/
```

Rilis versi baru: naikkan `__version__` di `src/alurkerja_sdk/__init__.py`, lalu
push tag `v<versi>`. GitHub Actions akan menjalankan test lalu membuat GitHub
Release berisi wheel dan sdist.
