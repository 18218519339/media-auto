from __future__ import annotations

import base64
import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


WECHAT_API_BASE = "https://api.weixin.qq.com"


class WeChatAPIError(Exception):
    def __init__(self, errcode: int, errmsg: str, url: str = ""):
        self.errcode = errcode
        self.errmsg = errmsg
        self.url = url
        super().__init__(f"WeChat API error {errcode}: {errmsg} (url: {url})")


@dataclass
class WeChatToken:
    access_token: str
    expires_at: float


@dataclass
class MediaUploadResult:
    media_id: str
    url: str | None


class WeChatClient:
    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id.strip()
        self.app_secret = app_secret.strip()
        self._token: WeChatToken | None = None

    def _request(self, method: str, path: str, payload: dict | None = None, token: str | None = None) -> dict:
        params = {}
        if token:
            params["access_token"] = token
        query = urllib.parse.urlencode(params) if params else ""
        url = f"{WECHAT_API_BASE}{path}"
        if query:
            url = f"{url}?{query}"

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
                if result.get("errcode") and result["errcode"] != 0:
                    raise WeChatAPIError(result["errcode"], result.get("errmsg", ""), url)
                return result
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            try:
                err = json.loads(body)
                raise WeChatAPIError(err.get("errcode", -1), err.get("errmsg", body), url) from exc
            except json.JSONDecodeError:
                raise WeChatAPIError(-1, body, url) from exc

    def get_access_token(self, force_refresh: bool = False) -> str:
        if not force_refresh and self._token and time.time() < self._token.expires_at - 60:
            return self._token.access_token

        result = self._request(
            "GET",
            "/cgi-bin/token?grant_type=client_credential&appid={}&secret={}".format(self.app_id, self.app_secret),
        )
        self._token = WeChatToken(
            access_token=result["access_token"],
            expires_at=time.time() + result.get("expires_in", 7200) - 120,
        )
        return self._token.access_token

    def upload_image_bytes(self, image_data: bytes, img_type: str = "image") -> str:
        """Upload raw image bytes to WeChat and return media_id."""
        token = self.get_access_token()
        url = f"{WECHAT_API_BASE}/cgi-bin/media/upload?access_token={token}&type={img_type}"

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        try:
            tmp.write(image_data)
            tmp.close()
            with open(tmp.name, "rb") as f:
                req = urllib.request.Request(
                    url,
                    data=f,
                    method="POST",
                    headers={"Content-Type": "image/png"},
                )
                try:
                    with urllib.request.urlopen(req, timeout=30) as response:
                        result = json.loads(response.read().decode("utf-8"))
                        if result.get("errcode"):
                            raise WeChatAPIError(result["errcode"], result.get("errmsg", ""), url)
                        return result["media_id"]
                finally:
                    pass
        finally:
            os.unlink(tmp.name)

    def upload_cover_image(self, image_path: str | None = None) -> str:
        if image_path:
            with open(image_path, "rb") as f:
                image_data = f.read()
        else:
            image_data = self._default_cover_bytes()
        return self.upload_image_bytes(image_data)

    def _default_cover_bytes(self) -> bytes:
        return base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )

    def add_draft(
        self,
        title: str,
        author: str | None,
        digest: str,
        content: str,
        thumb_media_id: str,
        need_open_comment: int = 0,
        only_fans_can_comment: int = 0,
    ) -> str:
        token = self.get_access_token()
        payload = {
            "articles": [
                {
                    "title": title,
                    "author": author or "",
                    "digest": digest,
                    "content": content,
                    "thumb_media_id": thumb_media_id,
                    "need_open_comment": need_open_comment,
                    "only_fans_can_comment": only_fans_can_comment,
                }
            ]
        }
        result = self._request(
            "POST",
            f"/cgi-bin/draft/add?access_token={token}",
            payload=payload,
        )
        media_id = result.get("media_id")
        if not media_id:
            raise WeChatAPIError(-1, "No media_id in draft/add response", "/cgi-bin/draft/add")
        return media_id

    def submit_draft_for_publishing(self, media_id: str) -> str:
        token = self.get_access_token()
        payload = {"media_id": media_id}
        result = self._request(
            "POST",
            "/cgi-bin/freepublish/submit?access_token={}".format(token),
            payload=payload,
        )
        publish_id = str(result.get("publish_id", ""))
        return publish_id

    def query_publish_result(self, publish_id: str) -> dict[str, Any]:
        token = self.get_access_token()
        return self._request(
            "GET",
            "/cgi-bin/freepublish/get?access_token={}&publish_id={}".format(token, publish_id),
        )

    def publish_draft(self, media_id: str, timeout: int = 60) -> dict[str, Any]:
        publish_id = self.submit_draft_for_publishing(media_id)
        deadline = time.time() + timeout
        while time.time() < deadline:
            result = self.query_publish_result(publish_id)
            status = result.get("publish_status", -1)
            if status == 0:
                article_id = result.get("msg_id", "")
                url = result.get("url", "")
                return {"publish_id": publish_id, "article_id": article_id, "url": url, "status": "succeeded"}
            elif status in (1, 2):
                time.sleep(2)
            else:
                raise WeChatAPIError(
                    int(status),
                    f"Publish status: {status}, detail: {result.get('detail', '')}",
                    "/cgi-bin/freepublish/get",
                )
        raise WeChatAPIError(-1, "Publish timed out", "/cgi-bin/freepublish/get")