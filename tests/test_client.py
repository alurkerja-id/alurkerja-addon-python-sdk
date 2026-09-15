import unittest

import requests

from alurkerja_sdk import (
    AlurkerjaAPIError,
    AlurkerjaConfigError,
    AlurkerjaRequestError,
    AlurkerjaSDK,
)

SVC = {
    "token": "secret-token",
    "baseurl": "http://asdb.com/api/v1",
    "tenant": {
        "id": 1,
        "name": "Tenant A",
        "slug": "tenant-a",
        "uuid": "f8672713-7ec0-4a8a-98ba-f6adf420d105",
        "trial_ends_at": "2026-12-31T00:00:00Z",
    },
    "extra": "value",
}


def make_response(status=200, body=b'{"ok": true}', content_type="application/json"):
    response = requests.Response()
    response.status_code = status
    response._content = body
    if content_type:
        response.headers["Content-Type"] = content_type
    return response


class FakeSession:
    def __init__(self, response=None, exc=None):
        # Response 4xx/5xx bernilai falsy, jadi jangan pakai `response or ...`.
        self.response = make_response() if response is None else response
        self.exc = exc
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if self.exc:
            raise self.exc
        return self.response


def make_sdk(svc=None, **session_kwargs):
    session = FakeSession(**session_kwargs)
    return AlurkerjaSDK(SVC if svc is None else svc, session=session), session


class ConfigTest(unittest.TestCase):
    def test_reads_svc_fields(self):
        sdk, _ = make_sdk()
        self.assertEqual(sdk.api_url, "http://asdb.com/api/v1")
        tenant = sdk.tenant
        self.assertEqual(
            (tenant.id, tenant.name, tenant.slug, tenant.uuid),
            (1, "Tenant A", "tenant-a", "f8672713-7ec0-4a8a-98ba-f6adf420d105"),
        )
        self.assertEqual(tenant.raw["trial_ends_at"], "2026-12-31T00:00:00Z")
        self.assertEqual(sdk.svc["extra"], "value")

    def test_base_url_variants_normalize_to_api_v1(self):
        for baseurl in (
            "http://asdb.com",
            "http://asdb.com/",
            "http://asdb.com/api/v1",
            "http://asdb.com/api/v1/",
            " http://asdb.com/API/V1 ",
        ):
            with self.subTest(baseurl=baseurl):
                sdk, _ = make_sdk({"token": "t", "baseurl": baseurl})
                self.assertEqual(sdk.api_url, "http://asdb.com/api/v1")

    def test_base_url_keeps_sub_path(self):
        sdk, _ = make_sdk({"token": "t", "baseurl": "https://asdb.com/gateway/api/v1"})
        self.assertEqual(sdk.api_url, "https://asdb.com/gateway/api/v1")

    def test_missing_or_invalid_config_raises(self):
        for svc in (
            {"baseurl": "http://asdb.com"},
            {"token": "  ", "baseurl": "http://asdb.com"},
            {"token": "t"},
            {"token": "t", "baseurl": "asdb.com"},
            {"token": "t", "baseurl": "ftp://asdb.com"},
            {"token": "t", "baseurl": "http://asdb.com", "tenant": "tenant-a"},
            "not json",
            ["token"],
        ):
            with self.subTest(svc=svc):
                with self.assertRaises(AlurkerjaConfigError):
                    AlurkerjaSDK(svc)

    def test_accepts_json_string(self):
        sdk = AlurkerjaSDK('{"token": "t", "baseurl": "http://asdb.com"}')
        self.assertEqual(sdk.api_url, "http://asdb.com/api/v1")
        self.assertIsNone(sdk.tenant)

    def test_tenant_id_string_is_converted(self):
        sdk, _ = make_sdk({"token": "t", "baseurl": "http://asdb.com", "tenant": {"id": "2", "slug": "b"}})
        self.assertEqual(sdk.tenant.id, 2)
        self.assertIsNone(sdk.tenant.uuid)

    def test_tenant_id_not_numeric_raises(self):
        with self.assertRaises(AlurkerjaConfigError):
            AlurkerjaSDK({"token": "t", "baseurl": "http://asdb.com", "tenant": {"id": "abc"}})

    def test_from_ctx_prefers_top_level_svc(self):
        other = dict(SVC, baseurl="http://other.com")
        sdk = AlurkerjaSDK.from_ctx({"svc": SVC, "configuration": {"svc": other}})
        self.assertEqual(sdk.api_url, "http://asdb.com/api/v1")

    def test_from_ctx_falls_back_to_configuration(self):
        sdk = AlurkerjaSDK.from_ctx({"configuration": {"svc": SVC}})
        self.assertEqual(sdk.tenant.slug, "tenant-a")

    def test_from_ctx_without_svc_raises(self):
        with self.assertRaises(AlurkerjaConfigError):
            AlurkerjaSDK.from_ctx({"configuration": {}})

    def test_repr_hides_token(self):
        sdk, _ = make_sdk()
        self.assertNotIn("secret-token", repr(sdk))


class UrlTest(unittest.TestCase):
    def test_builds_url_from_service_and_segments(self):
        sdk, session = make_sdk()
        sdk.post("probis", "masterdata", 1, "tenant-a")
        self.assertEqual(session.calls[0]["method"], "POST")
        self.assertEqual(session.calls[0]["url"], "http://asdb.com/api/v1/probis/masterdata/1/tenant-a")

    def test_encodes_special_characters(self):
        sdk, _ = make_sdk()
        self.assertEqual(
            sdk.build_url("probis", "masterdata", "a b?c#d"),
            "http://asdb.com/api/v1/probis/masterdata/a%20b%3Fc%23d",
        )

    def test_rejects_traversal_segments(self):
        sdk, session = make_sdk()
        for segment in ("", ".", "..", "a/b", "a\\b", None, True, 1.5):
            with self.subTest(segment=segment):
                with self.assertRaises(ValueError):
                    sdk.get("probis", "masterdata", segment)
        self.assertEqual(session.calls, [])

    def test_rejects_invalid_service_code(self):
        sdk, _ = make_sdk()
        for service in ("", "../probis", "probis/x", 1):
            with self.subTest(service=service):
                with self.assertRaises(ValueError):
                    sdk.get(service, "masterdata")


class RequestTest(unittest.TestCase):
    def test_each_method_sends_its_verb(self):
        sdk, session = make_sdk()
        for name in ("get", "post", "put", "patch", "delete"):
            getattr(sdk, name)("probis", "x")
        self.assertEqual([c["method"] for c in session.calls], ["GET", "POST", "PUT", "PATCH", "DELETE"])

    def test_sends_auth_and_tenant_headers(self):
        sdk, session = make_sdk()
        sdk.get("probis", "x", headers={"X-Custom": "1"})
        headers = session.calls[0]["headers"]
        self.assertEqual(headers["Authorization"], "Bearer secret-token")
        self.assertEqual(headers["x-active-tenant"], "tenant-a")
        self.assertEqual(headers["X-Custom"], "1")

    def test_does_not_double_bearer_prefix(self):
        sdk, session = make_sdk({"token": "Bearer abc", "baseurl": "http://asdb.com"})
        sdk.get("probis", "x")
        self.assertEqual(session.calls[0]["headers"]["Authorization"], "Bearer abc")
        self.assertNotIn("x-active-tenant", session.calls[0]["headers"])

    def test_post_sends_params_and_json_together(self):
        sdk, session = make_sdk()
        sdk.post(
            "probis", "masterdata", 1, "customers", "records",
            params={"upsert": True, "draft": False, "skip": None, "id": [1, None, 2]},
            json={"name": "PT A"},
        )
        call = session.calls[0]
        self.assertEqual(call["params"], {"upsert": "true", "draft": "false", "id": [1, 2]})
        self.assertEqual(call["json"], {"name": "PT A"})

    def test_uses_default_and_override_timeout(self):
        sdk, session = make_sdk()
        sdk.get("probis", "x")
        sdk.get("probis", "x", timeout=5)
        self.assertEqual([c["timeout"] for c in session.calls], [30.0, 5])


class ResponseTest(unittest.TestCase):
    def test_returns_parsed_json(self):
        sdk, _ = make_sdk(response=make_response(body=b'{"data": [1]}'))
        self.assertEqual(sdk.get("probis", "x"), {"data": [1]})

    def test_returns_text_bytes_or_none(self):
        cases = [
            (make_response(body=b"hello", content_type="text/plain"), "hello"),
            (make_response(body=b"\x89PNG", content_type="image/png"), b"\x89PNG"),
            (make_response(status=204, body=b""), None),
            (make_response(body=b"not json", content_type="application/json"), "not json"),
        ]
        for response, expected in cases:
            with self.subTest(expected=expected):
                sdk, _ = make_sdk(response=response)
                self.assertEqual(sdk.get("probis", "x"), expected)

    def test_non_2xx_raises_api_error(self):
        sdk, _ = make_sdk(response=make_response(status=403, body=b'{"error": "forbidden"}'))
        with self.assertRaises(AlurkerjaAPIError) as caught:
            sdk.delete("probis", "masterdata", 1, "customers")
        err = caught.exception
        self.assertEqual(err.status_code, 403)
        self.assertEqual(err.body, {"error": "forbidden"})
        self.assertEqual(err.method, "DELETE")
        self.assertNotIn("secret-token", str(err))

    def test_network_error_is_wrapped(self):
        sdk, _ = make_sdk(exc=requests.ConnectionError("refused"))
        with self.assertRaises(AlurkerjaRequestError) as caught:
            sdk.get("probis", "x")
        self.assertEqual(caught.exception.url, "http://asdb.com/api/v1/probis/x")


if __name__ == "__main__":
    unittest.main()
