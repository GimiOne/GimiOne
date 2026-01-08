from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

import httpx


class XUIError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Inbound:
    id: int
    remark: str
    port: int
    protocol: str
    settings: dict[str, Any]
    stream_settings: dict[str, Any]


class XUIClient:
    """
    Минимальный async-клиент для x-ui / 3x-ui.

    Сессия: cookie, авторизация через /login.
    """

    def __init__(self, *, base_url: str, username: str, password: str, timeout_sec: float = 15.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout_sec,
            headers={"User-Agent": "vpn-bot-mvp/1.0"},
            follow_redirects=True,
        )
        self._logged_in = False

    async def aclose(self) -> None:
        await self._client.aclose()

    async def login(self) -> None:
        resp = await self._client.post(
            "login",
            data={"username": self._username, "password": self._password},
        )
        if resp.status_code >= 400:
            raise XUIError(f"login failed: HTTP {resp.status_code}")
        data = _safe_json(resp)
        if isinstance(data, dict) and data.get("success") is False:
            raise XUIError(f"login failed: {data.get('msg')!r}")
        self._logged_in = True

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if not self._logged_in:
            await self.login()
        resp = await self._client.request(method, url, **kwargs)
        if resp.status_code in (401, 403):
            self._logged_in = False
            await self.login()
            resp = await self._client.request(method, url, **kwargs)
        return resp

    async def list_inbounds(self) -> list[Inbound]:
        resp = await self._request("GET", "panel/inbound/list")
        if resp.status_code >= 400:
            raise XUIError(f"list_inbounds failed: HTTP {resp.status_code}")
        data = _safe_json(resp)
        obj = _unwrap_xui_obj(data)
        items = obj.get("list") or obj.get("inbounds") or []
        res: list[Inbound] = []
        for it in items:
            try:
                res.append(_parse_inbound(it))
            except Exception:
                continue
        return res

    async def resolve_inbound(self, *, inbound_id: int | None, inbound_remark: str | None) -> Inbound:
        inbounds = await self.list_inbounds()
        if inbound_id is not None:
            for ib in inbounds:
                if ib.id == inbound_id:
                    return ib
            raise XUIError(f"inbound id not found: {inbound_id}")
        if inbound_remark:
            for ib in inbounds:
                if ib.remark == inbound_remark:
                    return ib
        for ib in inbounds:
            if ib.protocol.lower() == "vless":
                return ib
        raise XUIError("no suitable inbound found")

    async def add_client(
        self,
        *,
        inbound_id: int,
        client_uuid: str,
        email: str,
        expiry_time_ms: int,
        flow: str = "xtls-rprx-vision",
    ) -> None:
        payload = {
            "id": inbound_id,
            "settings": json.dumps(
                {
                    "clients": [
                        {
                            "id": client_uuid,
                            "email": email,
                            "flow": flow,
                            "limitIp": 0,
                            "totalGB": 0,
                            "expiryTime": int(expiry_time_ms),
                            "enable": True,
                        }
                    ]
                }
            ),
        }
        resp = await self._request("POST", "panel/inbound/addClient", json=payload)
        if resp.status_code >= 400:
            raise XUIError(f"add_client failed: HTTP {resp.status_code}")
        data = _safe_json(resp)
        if isinstance(data, dict) and data.get("success") is False:
            raise XUIError(f"add_client failed: {data.get('msg')!r}")

    async def delete_client(self, *, inbound_id: int, client_uuid: str) -> None:
        """
        У 3x-ui встречаются разные варианты.
        Пробуем наиболее распространённые, без "магии" с интерактивом.
        """
        # variant A
        resp = await self._request("POST", f"panel/inbound/delClient/{inbound_id}/{client_uuid}")
        if resp.status_code < 400:
            return

        # variant B
        resp = await self._request("POST", "panel/inbound/delClient", json={"id": inbound_id, "clientId": client_uuid})
        if resp.status_code >= 400:
            raise XUIError(f"delete_client failed: HTTP {resp.status_code}")
        data = _safe_json(resp)
        if isinstance(data, dict) and data.get("success") is False:
            raise XUIError(f"delete_client failed: {data.get('msg')!r}")

    @staticmethod
    def build_vless_reality_uri(*, inbound: Inbound, vpn_public_host: str, client_uuid: str, label: str) -> str:
        """
        Генерация VLESS Reality URI для популярных клиентов (v2rayNG / v2rayN / Clash Meta).
        """
        port = int(inbound.port)
        stream = inbound.stream_settings
        if not isinstance(stream, dict):
            stream = {}
        tls = stream.get("tlsSettings") if isinstance(stream.get("tlsSettings"), dict) else {}
        reality = (
            stream.get("realitySettings")
            or tls.get("realitySettings")
            or stream.get("reality")
            or {}
        )

        pbk = reality.get("publicKey") or reality.get("public_key") or ""
        server_names = reality.get("serverNames") or reality.get("server_names") or []
        short_ids = reality.get("shortIds") or reality.get("short_ids") or []
        fp = reality.get("fingerprint") or "chrome"
        spx = reality.get("spiderX") or reality.get("spider_x") or None

        sni = server_names[0] if isinstance(server_names, list) and server_names else ""
        sid = short_ids[0] if isinstance(short_ids, list) and short_ids else ""

        query = {
            "type": "tcp",
            "security": "reality",
            "encryption": "none",
            "flow": "xtls-rprx-vision",
            "fp": fp,
            "sni": sni,
            "pbk": pbk,
            "sid": sid,
        }
        if spx:
            query["spx"] = spx

        return f"vless://{client_uuid}@{vpn_public_host}:{port}?{urlencode(query, quote_via=quote)}#{quote(label)}"


def new_client_uuid() -> str:
    return str(uuid.uuid4())


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return None


def _unwrap_xui_obj(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        if "obj" in data and isinstance(data["obj"], dict):
            return data["obj"]
        return data
    return {}


def _parse_inbound(item: dict[str, Any]) -> Inbound:
    settings_raw = item.get("settings") or "{}"
    stream_raw = item.get("streamSettings") or "{}"
    settings = json.loads(settings_raw) if isinstance(settings_raw, str) else (settings_raw or {})
    stream = json.loads(stream_raw) if isinstance(stream_raw, str) else (stream_raw or {})

    return Inbound(
        id=int(item.get("id")),
        remark=str(item.get("remark") or ""),
        port=int(item.get("port") or 0),
        protocol=str(item.get("protocol") or ""),
        settings=settings if isinstance(settings, dict) else {},
        stream_settings=stream if isinstance(stream, dict) else {},
    )

