"""Fake HTTP request/file objects for testing function_app.py handlers.

Duck-typed instead of constructing real azure.functions.HttpRequest with real multipart
bodies — handlers only ever touch .method/.headers/.params/.route_params/.files/.get_json().
"""
import io


class FakeFile:
    def __init__(self, filename: str, content_type: str, data: bytes):
        self.filename = filename
        self.content_type = content_type
        self.stream = io.BytesIO(data)


class FakeRequest:
    def __init__(self, method="GET", headers=None, params=None, route_params=None, json_body=None, files=None):
        self.method = method
        self.headers = headers or {}
        self.params = params or {}
        self.route_params = route_params or {}
        self._json_body = json_body
        self.files = files or {}

    def get_json(self):
        if self._json_body is None:
            raise ValueError("no JSON body in request")
        return self._json_body


def allow_user(role="user", user_id="u1", email="u1@x.com", extra=None):
    """user dict ที่ guard.gate mock คืนให้ — ผ่านทุกอย่าง (ใช้คู่กับ patch guard.gate return (user, None))."""
    u = {"user_id": user_id, "email": email, "name": user_id, "role": role, "authenticated": True, "ip": "10.0.0.1"}
    if extra:
        u.update(extra)
    return u
