"""高德 POI 图片服务测试。"""

import httpx

from app.services.amap_photo_service import AmapPhotoService


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_returns_exact_poi_photo_first(monkeypatch):
    def fake_get(url, params, timeout):
        assert url == AmapPhotoService.BASE_URL
        assert params["keywords"] == "陈家祠"
        assert params["city"] == "广州"
        assert params["extensions"] == "all"
        assert timeout == 10.0
        return FakeResponse({
            "status": "1",
            "pois": [
                {"name": "陈家祠地铁站", "photos": [{"url": "https://example.com/station.jpg"}]},
                {"name": "陈家祠", "photos": [{"url": "https://example.com/chen-clan.jpg"}]},
            ],
        })

    monkeypatch.setattr(httpx, "get", fake_get)

    service = AmapPhotoService(api_key="test-key")
    assert service.get_photo_url("陈家祠", "广州") == "https://example.com/chen-clan.jpg"


def test_returns_none_when_poi_has_no_photo(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *args, **kwargs: FakeResponse({"status": "1", "pois": [{"name": "测试景点"}]}),
    )

    service = AmapPhotoService(api_key="test-key")
    assert service.get_photo_url("测试景点") is None


def test_hides_request_url_when_http_call_fails(monkeypatch, capsys):
    def raise_error(*args, **kwargs):
        request = httpx.Request("GET", "https://example.com/?key=secret")
        raise httpx.ConnectError("failed", request=request)

    monkeypatch.setattr(httpx, "get", raise_error)

    service = AmapPhotoService(api_key="test-key")
    assert service.get_photo_url("测试景点") is None
    output = capsys.readouterr().out
    assert "ConnectError" in output
    assert "secret" not in output
