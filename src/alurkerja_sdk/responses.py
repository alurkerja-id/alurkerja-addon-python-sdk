"""Pembentuk response script addon (jalur service task BPMN).

Platform membaca stdout script sebagai JSON dan me-merge key top-level-nya ke
`variables` proses. Modul ini menjaga bentuknya tetap sama di semua script:
`status`, `message`, `data`, `runkey`, tanpa perlu dirakit ulang tiap kali.

Dipakai lewat instance SDK (`sdk.success(...)`, `sdk.error(...)`) atau langsung
(`success(...)`, `error(...)`) saat SDK belum sempat dibuat — mis. `svc` tidak
lengkap sehingga `AlurkerjaSDK.from_ctx` melempar `AlurkerjaConfigError`.

Kontrak jalur `apis` (`status` dipetakan ke HTTP status) BERBEDA dan belum
ditangani di sini.
"""

from typing import Any, Mapping, Optional

from .errors import AlurkerjaAPIError, AlurkerjaConfigError, AlurkerjaRequestError

STATUS_OK = "ok"
STATUS_ERROR = "error"

# Jenis kegagalan, dibaca Camunda (AlurkerjaIntegrationContext):
#   RUNTIME_ERROR -> incident di Cockpit, bisa di-retry operator.
#   BPMN_ERROR    -> BpmnError dengan kode `error`, ditangkap error boundary
#                    event di diagram. Ini kegagalan BISNIS yang alurnya sudah
#                    digambar, bukan gangguan teknis.
TYPE_RUNTIME_ERROR = "RUNTIME_ERROR"
TYPE_BPMN_ERROR = "BPMN_ERROR"

# Kode error bawaan, dipakai juga oleh script sebagai nilai field `error`.
ERROR_API = "API_ERROR"
ERROR_CONFIGURATION = "INVALID_CONFIGURATION"
ERROR_REQUEST = "REQUEST_FAILED"
ERROR_EXECUTION = "EXECUTION_ERROR"

# Exit code mengikuti konvensi General Action Executor:
# 0 sukses, 1 business error, 2 invalid input, >2 runtime/system error.
EXIT_OK = 0
EXIT_BUSINESS_ERROR = 1
EXIT_INVALID_INPUT = 2
EXIT_RUNTIME_ERROR = 3


def success(
    data: Any = None,
    message: Optional[str] = None,
    runkey: Optional[str] = None,
    **extra: Any,
) -> dict:
    """Response sukses: `{"status": "ok", ...}`.

    Args:
        data: Muatan yang ditaruh di `data`. Diabaikan kalau None.
        message: Pesan untuk operator; opsional.
        runkey: Runkey eksekusi. Lewat `sdk.success(...)` terisi otomatis.
        **extra: Key tambahan di TOP-LEVEL, yaitu yang di-merge ke `variables`
            proses — mis. `sdk.success(records, total=10)`.
    """
    response = {"status": STATUS_OK}
    if message is not None:
        response["message"] = message
    if data is not None:
        response["data"] = data
    return _finalize(response, runkey, extra)


def error(
    message: Any,
    code: Optional[str] = None,
    data: Any = None,
    runkey: Optional[str] = None,
    **extra: Any,
) -> dict:
    """Response gagal: `{"status": "error", "message": ..., "error": ...}`.

    `message` boleh berupa exception. Untuk exception SDK, `code` dan detail
    tambahan (`http_status`, `response`) diisi otomatis:

        except AlurkerjaAPIError as err:
            return sdk.error(err)
    """
    detail = {}
    if isinstance(message, BaseException):
        code = code or _code_for(message)
        detail = _detail_for(message)
        message = str(message)

    response = {
        "status": STATUS_ERROR,
        "type": TYPE_RUNTIME_ERROR,
        "message": message,
        "error": code or ERROR_EXECUTION,
    }
    response.update(detail)
    if data is not None:
        response["data"] = data
    return _finalize(response, runkey, extra)


def bpmn_error(
    code: str,
    message: Optional[str] = None,
    data: Any = None,
    runkey: Optional[str] = None,
    **extra: Any,
) -> dict:
    """Kegagalan BISNIS yang ditangkap diagram: `{"type": "BPMN_ERROR", ...}`.

    Camunda melemparnya sebagai `BpmnError` dengan `errorCode = code`, sehingga
    error boundary event dengan kode yang sama menangkapnya dan proses lanjut
    lewat jalur error — bukan berhenti sebagai incident.

        return sdk.bpmn_error("STOK_HABIS", "Stok barang tidak mencukupi")

    Pastikan `code` sama dengan Error Code di boundary event; tanpa boundary
    event yang cocok, Camunda tetap membuat incident.
    """
    response = {
        "status": STATUS_ERROR,
        "type": TYPE_BPMN_ERROR,
        "error": code,
    }
    if message is not None:
        response["message"] = message
    if data is not None:
        response["data"] = data
    return _finalize(response, runkey, extra)


def exit_code_for(response: Mapping[str, Any]) -> int:
    """Exit code yang cocok untuk satu response.

    Dipakai di `main()`: `sys.exit(exit_code_for(result))`. Response sukses
    menghasilkan 0; kegagalan mengikuti jenis errornya.
    """
    if response.get("status") == STATUS_OK:
        return EXIT_OK
    if response.get("type") == TYPE_BPMN_ERROR:
        # Bukan kegagalan eksekusi: script berhasil memutuskan bahwa alur harus
        # berbelok. Exit non-zero akan membuat integration-service menjawab 500
        # dan Camunda membuat incident sebelum sempat membaca BPMN_ERROR-nya.
        return EXIT_OK
    return {
        ERROR_CONFIGURATION: EXIT_INVALID_INPUT,
        ERROR_REQUEST: EXIT_RUNTIME_ERROR,
    }.get(response.get("error"), EXIT_BUSINESS_ERROR)


def _finalize(response: dict, runkey: Optional[str], extra: Mapping[str, Any]) -> dict:
    for key, value in extra.items():
        # Key bentukan sendiri tidak boleh menimpa field kontrak.
        if key in ("status", "type", "message", "error", "data", "runkey"):
            raise ValueError(f"key '{key}' sudah dipakai kontrak response; pakai data= untuk isinya")
        response[key] = value
    if runkey:
        response["runkey"] = runkey
    return response


def _code_for(exc: BaseException) -> str:
    if isinstance(exc, AlurkerjaAPIError):
        return ERROR_API
    if isinstance(exc, AlurkerjaConfigError):
        return ERROR_CONFIGURATION
    if isinstance(exc, AlurkerjaRequestError):
        return ERROR_REQUEST
    return ERROR_EXECUTION


def _detail_for(exc: BaseException) -> dict:
    if isinstance(exc, AlurkerjaAPIError):
        return {"http_status": exc.status_code, "response": exc.body}
    return {}


__all__ = [
    "success",
    "error",
    "bpmn_error",
    "exit_code_for",
    "STATUS_OK",
    "STATUS_ERROR",
    "TYPE_RUNTIME_ERROR",
    "TYPE_BPMN_ERROR",
    "ERROR_API",
    "ERROR_CONFIGURATION",
    "ERROR_REQUEST",
    "ERROR_EXECUTION",
    "EXIT_OK",
    "EXIT_BUSINESS_ERROR",
    "EXIT_INVALID_INPUT",
    "EXIT_RUNTIME_ERROR",
]
