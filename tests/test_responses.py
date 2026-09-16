import unittest

from alurkerja_sdk import (
    AlurkerjaAPIError,
    AlurkerjaConfigError,
    AlurkerjaRequestError,
    AlurkerjaSDK,
    bpmn_error,
    error,
    exit_code_for,
    success,
)

CTX = {
    "runkey": "exec-1789-getMasterDataRecords",
    "parameters": {"slug": "customers"},
    "svc": {"token": "t", "baseurl": "http://asdb.com", "tenant": {"id": 1, "slug": "tenant-a"}},
}


def make_sdk(ctx=None):
    return AlurkerjaSDK.from_ctx(CTX if ctx is None else ctx)


class SuccessTest(unittest.TestCase):
    def test_minimal(self):
        self.assertEqual(success(), {"status": "ok"})

    def test_data_and_message(self):
        self.assertEqual(
            success([{"id": 1}], message="1 record", runkey="r"),
            {"status": "ok", "message": "1 record", "data": [{"id": 1}], "runkey": "r"},
        )

    def test_extra_keys_stay_top_level(self):
        # Key top-level adalah yang di-merge ke variables proses.
        self.assertEqual(
            success({"a": 1}, total=2, last_sync="2026-09-16"),
            {"status": "ok", "data": {"a": 1}, "total": 2, "last_sync": "2026-09-16"},
        )

    def test_falsy_data_still_included(self):
        self.assertEqual(success([]), {"status": "ok", "data": []})
        self.assertEqual(success(0), {"status": "ok", "data": 0})

    def test_extra_cannot_override_contract(self):
        for key in ("status", "type", "error"):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    success({"a": 1}, **{key: "x"})


class ErrorTest(unittest.TestCase):
    def test_message_and_code(self):
        self.assertEqual(
            error("slug wajib diisi", code="MISSING_PARAMETER", runkey="r"),
            {
                "status": "error",
                "type": "RUNTIME_ERROR",
                "message": "slug wajib diisi",
                "error": "MISSING_PARAMETER",
                "runkey": "r",
            },
        )

    def test_default_code(self):
        self.assertEqual(error("gagal")["error"], "EXECUTION_ERROR")

    def test_from_api_error(self):
        response = error(AlurkerjaAPIError(403, {"error": "forbidden"}, "GET", "http://x/records"))
        self.assertEqual(response["error"], "API_ERROR")
        self.assertEqual(response["http_status"], 403)
        self.assertEqual(response["response"], {"error": "forbidden"})
        self.assertIn("HTTP 403", response["message"])

    def test_from_other_sdk_errors(self):
        self.assertEqual(error(AlurkerjaConfigError("svc.token wajib diisi"))["error"], "INVALID_CONFIGURATION")
        self.assertEqual(error(AlurkerjaRequestError("timeout", "GET", "http://x"))["error"], "REQUEST_FAILED")
        self.assertEqual(error(ValueError("segmen path tidak sah"))["error"], "EXECUTION_ERROR")

    def test_explicit_code_wins_over_exception(self):
        response = error(AlurkerjaAPIError(404, None, "GET", "http://x"), code="DATA_NOT_FOUND")
        self.assertEqual(response["error"], "DATA_NOT_FOUND")
        self.assertEqual(response["http_status"], 404)

    def test_data_for_business_detail(self):
        response = error("Record ditolak", code="REJECTED", data={"reason": "duplikat"})
        self.assertEqual(response["data"], {"reason": "duplikat"})


class BpmnErrorTest(unittest.TestCase):
    def test_shape(self):
        self.assertEqual(
            bpmn_error("STOK_HABIS", "Stok barang tidak mencukupi", runkey="r"),
            {
                "status": "error",
                "type": "BPMN_ERROR",
                "error": "STOK_HABIS",
                "message": "Stok barang tidak mencukupi",
                "runkey": "r",
            },
        )

    def test_code_only(self):
        self.assertEqual(bpmn_error("STOK_HABIS"), {"status": "error", "type": "BPMN_ERROR", "error": "STOK_HABIS"})

    def test_data_and_extra(self):
        response = bpmn_error("STOK_HABIS", data={"tersedia": 2}, requested=5)
        self.assertEqual(response["data"], {"tersedia": 2})
        self.assertEqual(response["requested"], 5)

    def test_error_default_type_is_runtime(self):
        self.assertEqual(error("gagal")["type"], "RUNTIME_ERROR")
        self.assertNotIn("type", success())

    def test_sdk_method_and_alias(self):
        sdk = make_sdk()
        response = sdk.bpmn_error("STOK_HABIS", "habis")
        self.assertEqual(response["type"], "BPMN_ERROR")
        self.assertEqual(response["runkey"], CTX["runkey"])
        self.assertEqual(sdk.bpmnError("STOK_HABIS", "habis"), response)


class ExitCodeTest(unittest.TestCase):
    def test_exit_codes(self):
        cases = [
            (success(), 0),
            (error("gagal"), 1),
            (error("x", code="MISSING_PARAMETER"), 1),
            (error(AlurkerjaConfigError("svc")), 2),
            (error(AlurkerjaRequestError("timeout", "GET", "http://x")), 3),
            # BPMN_ERROR harus exit 0: kalau non-zero, integration-service
            # menjawab 500 dan Camunda membuat incident, bukan melempar BpmnError.
            (bpmn_error("STOK_HABIS"), 0),
        ]
        for response, expected in cases:
            with self.subTest(response=response):
                self.assertEqual(exit_code_for(response), expected)


class SDKMethodTest(unittest.TestCase):
    def test_runkey_from_ctx(self):
        sdk = make_sdk()
        self.assertEqual(sdk.runkey, "exec-1789-getMasterDataRecords")
        self.assertEqual(sdk.success({"a": 1})["runkey"], "exec-1789-getMasterDataRecords")
        self.assertEqual(sdk.error("gagal")["runkey"], "exec-1789-getMasterDataRecords")

    def test_without_runkey_in_ctx(self):
        sdk = AlurkerjaSDK.from_ctx({"svc": CTX["svc"]})
        self.assertIsNone(sdk.runkey)
        self.assertNotIn("runkey", sdk.success({"a": 1}))

    def test_explicit_runkey_argument(self):
        sdk = AlurkerjaSDK(CTX["svc"], runkey="manual")
        self.assertEqual(sdk.success()["runkey"], "manual")

    def test_response_never_contains_token(self):
        sdk = make_sdk()
        for response in (sdk.success({"a": 1}), sdk.error("gagal")):
            with self.subTest(response=response):
                self.assertNotIn("svc", response)
                self.assertNotIn("t", [response.get("token")])


if __name__ == "__main__":
    unittest.main()
