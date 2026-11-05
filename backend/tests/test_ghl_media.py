import uuid
from types import SimpleNamespace

import pytest

from app.core.exceptions import ConflictError
from app.services.ghl_client import GHLAPIError
from app.services.ghl_media_service import GHLMediaService, media_url


class _DB:
    def __init__(self, location="loc-1"):
        self.operator = SimpleNamespace(ghl_location_id=location)

    def get(self, _model, _id):
        return self.operator


def _service(response=None, error=None, location="loc-1"):
    service = GHLMediaService.__new__(GHLMediaService)
    service.db = _DB(location)
    service.operator_id = uuid.uuid4()
    calls = []

    def upload_media(**kwargs):
        calls.append(kwargs)
        if error:
            raise error
        return response or {"fileId": "f1", "url": "https://assets.example/f1.jpg"}

    service.client = SimpleNamespace(upload_media=upload_media)
    return service, calls


def test_image_upload_returns_the_highlevel_link():
    service, calls = _service()
    url = service.upload(filename="Kayak tour.jpg", content=b"x" * 10, content_type="image/jpeg")
    assert url == "https://assets.example/f1.jpg"
    assert calls[0]["name"] == "Kayak-tour.jpg"


def test_unsupported_and_oversized_files_are_refused():
    service, _ = _service()
    with pytest.raises(ConflictError):
        service.upload(filename="a.pdf", content=b"x", content_type="application/pdf")
    with pytest.raises(ConflictError):
        service.upload(filename="a.mp4", content=b"x" * (5 * 1024 * 1024), content_type="video/mp4")


def test_import_downloads_the_file_and_uploads_a_copy():
    service, calls = _service()
    service._download = lambda url: (b"jpegbytes", "image/jpeg")
    url = service.import_url("https://cdn.filestackcontent.com/iQUAMLZ2SC6MQ4CZmvzQ")
    assert url == "https://assets.example/f1.jpg"
    assert calls[0]["name"] == "iQUAMLZ2SC6MQ4CZmvzQ.jpg"
    assert calls[0]["content"] == b"jpegbytes" and "file_url" not in calls[0]
    with pytest.raises(ConflictError):
        service.import_url("http://insecure.example/a.jpg")


def test_internal_addresses_are_never_fetched(monkeypatch):
    from app.services import ghl_media_service

    monkeypatch.setattr(ghl_media_service.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("169.254.169.254", 443))])
    service, _ = _service()
    with pytest.raises(ConflictError, match="can't be downloaded"):
        service._download("https://metadata.example/latest")


def test_missing_scope_explains_how_to_fix_it():
    service, _ = _service(error=GHLAPIError("forbidden", status_code=403))
    with pytest.raises(ConflictError, match="medias.write"):
        service.upload(filename="a.jpg", content=b"x", content_type="image/jpeg")


def test_media_url_accepts_either_response_shape():
    assert media_url({"url": "https://a"}) == "https://a"
    assert media_url({"file": {"url": "https://b"}}) == "https://b"
