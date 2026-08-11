"""高德地图 POI 图片服务。"""

from typing import Optional

import httpx

from ..config import get_settings


class AmapPhotoService:
    """根据景点名称查询高德 POI 图片。"""

    BASE_URL = "https://restapi.amap.com/v3/place/text"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key if api_key is not None else get_settings().amap_api_key
        if not self.api_key:
            raise ValueError("高德地图API Key未配置,请在.env文件中设置AMAP_API_KEY")

    def get_photo_url(self, name: str, city: Optional[str] = None) -> Optional[str]:
        """返回最匹配 POI 的第一张图片 URL，没有图片时返回 None。"""
        params = {
            "key": self.api_key,
            "keywords": name,
            "extensions": "all",
            "offset": 10,
            "page": 1,
        }
        if city:
            params.update({"city": city, "citylimit": "true"})

        try:
            response = httpx.get(self.BASE_URL, params=params, timeout=10.0)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            # 不输出包含 API Key 的完整请求 URL。
            print(f"❌ 高德POI图片查询失败: {type(error).__name__}")
            return None

        if payload.get("status") != "1":
            print(f"❌ 高德POI图片查询失败: {payload.get('info', '未知错误')}")
            return None

        pois = payload.get("pois") or []
        exact_matches = [poi for poi in pois if poi.get("name") == name]
        candidates = exact_matches + [poi for poi in pois if poi not in exact_matches]

        for poi in candidates:
            for photo in poi.get("photos") or []:
                photo_url = photo.get("url")
                if photo_url:
                    return photo_url

        return None


_amap_photo_service = None


def get_amap_photo_service() -> AmapPhotoService:
    """获取高德 POI 图片服务单例。"""
    global _amap_photo_service

    if _amap_photo_service is None:
        _amap_photo_service = AmapPhotoService()

    return _amap_photo_service
