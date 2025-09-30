import os, sys
import pytest
import requests

# quick and dirty hack to NOT make /tests dir a package
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class DummyResp:
    def __init__(self, ok=True, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {"ok": ok, "result": {"message_id": 1}}

    def raise_for_status(self):
        if not (200 <= self.status_code < 300):
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


class FakeRequests:
    request_exception = requests.RequestException
    def __init__(self):
        self.calls = []
    def post(self, url, data=None, files=None, timeout=None):
        self.calls.append((url, data, bool(files)))
        return DummyResp(ok=True, status=200)


class BrokenRequests(FakeRequests):
    def post(self, *a, **k):
        raise self.request_exception("network down")


def fake_runner_ok(cmd, timeout=30):
    class P:
        stdout = "hello\n"
        stderr = ""
    return P()


def fake_runner_no_stdout(cmd, timeout=30):
    class P:
        stdout = ""
        stderr = "oops\n"
    return P()


@pytest.fixture
def fake_requests():
    return FakeRequests()

@pytest.fixture
def broken_requests():
    return BrokenRequests()

@pytest.fixture
def runner_ok():
    return fake_runner_ok

@pytest.fixture
def runner_no_stdout():
    return fake_runner_no_stdout
