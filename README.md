# alurkerja-sdk

SDK Python untuk script addon AlurKerja. Script cukup menerima `svc` dari
platform, lalu memanggil service AlurKerja (mis. master data di `probis`) tanpa
merakit URL, header auth, atau header tenant sendiri.

## Dari mana `svc` datang

Addon yang opt-in di `index.json`:

```json
{ "name": "mockapi", "svc": { "enabled": true } }
```

menerima `ctx["svc"]` saat script dijalankan dari service task BPMN. Token-nya milik
user yang men-deploy versi BPMN yang sedang berjalan (role minimal admin SOP),
dibuat otomatis oleh integration-service. Addon tanpa opt-in tidak menerima `svc`.

## Instalasi

```bash
pip install "git+https://github.com/alurkerja-id/alurkerja-addon-python-sdk.git@v0.3.0"
```

Lewat SSH:

```bash
pip install "git+ssh://git@github.com/alurkerja-id/alurkerja-addon-python-sdk.git@v0.3.0"
```

Di `requirements.txt`:

```text
alurkerja-sdk @ git+https://github.com/alurkerja-id/alurkerja-addon-python-sdk.git@v0.3.0
```

## Pemakaian

```python
import sys

from alurkerja_sdk import AlurkerjaSDK, AlurkerjaAPIError


def run(ctx):
    sdk = AlurkerjaSDK.from_ctx(ctx)          # membaca ctx["svc"]

    # BPMN yang sedang berjalan, mis. untuk logging
    print(f"{sdk.process.key} v{sdk.process.version} @ {sdk.process.activity_id} as {sdk.actor.email}", file=sys.stderr)

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
  },
  "process": {
    "definitionId": "pengajuan-cuti:7:3f1c...",
    "key": "pengajuan-cuti",
    "name": "Pengajuan Cuti",
    "version": 7,
    "deploymentId": "a41b...",
    "tenantId": "f8672713-...",
    "instanceId": "9c2e...",
    "businessKey": "CUTI-2026-001",
    "activityId": "Activity_ambil_md",
    "activityName": "Ambil Master Data"
  },
  "actor": { "email": "deployer@example.com", "source": "deployer" }
}
```

| Key | Wajib | Keterangan |
|---|---|---|
| `token` | ya | Dikirim sebagai `Authorization: Bearer <token>`. Prefix `Bearer ` boleh ada atau tidak. |
| `baseurl` | ya | `http://host`, `http://host/api/v1`, dan slash di akhir semuanya dianggap sama. |
| `tenant` | tidak | Mengikuti JSON `models.Tenant` di tenant-management-service. Dibaca sebagai `sdk.tenant.id/.name/.slug/.uuid`; field lain lewat `sdk.tenant.raw`. Kalau ada `slug`, dikirim sebagai header `x-active-tenant`. |
| `process` | tidak | BPMN yang sedang berjalan: `sdk.process.definition_id/.key/.name/.version/.deployment_id/.tenant_id/.instance_id/.business_key/.activity_id/.activity_name`; aslinya lewat `sdk.process.raw`. |
| `actor` | tidak | Pemilik token: `sdk.actor.email`, `sdk.actor.source`. |
| lainnya | tidak | Tetap bisa dibaca lewat `sdk.svc["..."]`. |

`svc` juga boleh berupa string JSON. `from_ctx` mencari `ctx["svc"]` lebih dulu,
lalu `ctx["configuration"]["svc"]` (untuk pengujian lokal atau addon lama).

Token berumur pendek: buat `AlurkerjaSDK` di dalam `run(ctx)` dari ctx yang diterima,
jangan disimpan antar eksekusi.

### Membentuk response script

Bentuk balasan script diurus SDK, termasuk `runkey` dan key `type` untuk kegagalan:

```python
def run(ctx):
    sdk = AlurkerjaSDK.from_ctx(ctx)

    if not slug:
        return sdk.error("slug wajib diisi", code="MISSING_PARAMETER")

    try:
        records = sdk.get("probis", "masterdata", sdk.tenant.id, slug, "records")
    except AlurkerjaAPIError as err:
        return sdk.error(err)                     # error/http_status/response terisi sendiri

    if not records["content"]:
        return sdk.bpmn_error("DATA_KOSONG", "Master data belum berisi record")

    return sdk.success(records, message="Master data terbaca", total=records["totalElements"])
```

| Method | Hasil | `type` | Exit code |
| --- | --- | :---: | :---: |
| `sdk.success(data=None, message=None, **extra)` | `{"status": "ok", "message": …, "data": …, "runkey": …}` | — | 0 |
| `sdk.error(message_or_exception, code=None, data=None, **extra)` | `{"status": "error", "type": "RUNTIME_ERROR", "message": …, "error": …}` | `RUNTIME_ERROR` | 1 / 2 / 3 |
| `sdk.bpmn_error(code, message=None, data=None, **extra)` | `{"status": "error", "type": "BPMN_ERROR", "error": code, …}` | `BPMN_ERROR` | 0 |

- **`**extra`** menambah key di **top-level**, yaitu yang di-merge ke `variables` proses.
- **`RUNTIME_ERROR`** = gangguan teknis → incident di Cockpit, bisa di-retry operator.
- **`BPMN_ERROR`** = kegagalan bisnis → Camunda melempar `BpmnError` dengan `errorCode = code`, ditangkap error boundary event berkode sama. Exit code-nya 0, karena exit non-zero membuat platform menjawab 500 dan proses berhenti sebagai incident.
- `exit_code_for(response)` dipakai di `main()`: `sys.exit(exit_code_for(result))`.
- Tersedia juga sebagai fungsi modul (`success`, `error`, `bpmn_error`, `exit_code_for`) untuk dipakai saat SDK belum sempat dibuat, mis. `svc` tidak lengkap. Di situ `runkey=` diisi manual.
- Alias `sdk.bpmnError(...)` tersedia supaya penamaannya sama dengan istilah di diagram.

### Method HTTP

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

## Changelog

- **0.3.0** — `sdk.success()`, `sdk.error()`, `sdk.bpmn_error()`, dan `exit_code_for()`: bentuk response script (termasuk key `type`: `RUNTIME_ERROR` / `BPMN_ERROR`) diurus SDK.
- **0.2.1** — Mendukung Python 3.8 (`python3` bawaan Ubuntu 20.04).
- **0.2.0** — `sdk.process` dan `sdk.actor` dari `svc.process` / `svc.actor`.
- **0.1.0** — Rilis awal: klien HTTP, `svc.tenant`, header `x-active-tenant`.

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
