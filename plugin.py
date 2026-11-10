"""Voyage multimodal embedding ↔ MaiBot OpenAI-compatible image embedding adapter."""

from __future__ import annotations

import base64
import math
import struct
import re
from typing import Any, ClassVar

from aiohttp import ClientSession, ClientTimeout, web
from maibot_sdk import Field, MaiBotPlugin, PluginConfigBase

DATA_URI = re.compile(r"^data:image/(?:png|jpeg|jpg|webp|gif);base64,([A-Za-z0-9+/=]+)$", re.I)
VOYAGE_URL = "https://api.voyageai.com/v1/multimodalembeddings"


class BridgeOptions(PluginConfigBase):
    config_version: str = Field(default="0.1.0", json_schema_extra={"hidden": True})


class BridgeConfig(PluginConfigBase):
    plugin: BridgeOptions = Field(default_factory=BridgeOptions)
    port: int = Field(default=18765, ge=1024, le=65535, description="僅在本機監聽的轉接埠")


class VoyageImageBridge(MaiBotPlugin):
    config_model: ClassVar[type[PluginConfigBase] | None] = BridgeConfig

    async def on_load(self) -> None:
        app = web.Application(client_max_size=20 * 1024**2)
        app.router.add_post("/v1/embeddings", self._embeddings)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        try:
            self._site = web.TCPSite(self._runner, "127.0.0.1", self.config.port)
            await self._site.start()
        except Exception:
            await self._runner.cleanup()
            raise
        self.ctx.logger.info("Voyage 圖片嵌入轉接器已在 127.0.0.1:%s 啟動", self.config.port)

    async def on_unload(self) -> None:
        if hasattr(self, "_runner"):
            await self._runner.cleanup()

    async def on_config_update(self, scope: str = "", config_data: dict[str, Any] | None = None, version: str = "") -> None:
        """變更埠需重啟插件 Runner。"""
        return None

    async def _embeddings(self, request: web.Request) -> web.Response:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or not auth[7:].strip():
            return web.json_response({"error": {"message": "需要 Voyage Bearer API key"}}, status=401)
        try:
            body = await request.json()
            model = body["model"]
            image = body["input"]
            if not isinstance(model, str) or not model.startswith("voyage-multimodal-"):
                raise ValueError("只支援 voyage-multimodal-* 模型")
            if not isinstance(image, dict) or set(image) != {"image"} or not isinstance(image["image"], str):
                raise ValueError("input 須為 {image: data URI}；請設定 image_embedding_input")
            match = DATA_URI.fullmatch(image["image"])
            if not match or len(base64.b64decode(match[1], validate=True)) > 15 * 1024**2:
                raise ValueError("圖片須是 15 MB 以下的 base64 data URI")
            allowed = {"input_type", "output_dimension", "truncation"}
            if set(body) - {"model", "input", "encoding_format"} - allowed:
                raise ValueError("不支援的圖片嵌入參數")
            encoding = body.get("encoding_format", "float")
            if encoding not in ("float", "base64"):
                raise ValueError("不支援的向量編碼")
        except (ValueError, KeyError, TypeError, base64.binascii.Error) as exc:
            return web.json_response({"error": {"message": str(exc)}}, status=400)
        payload = {
            "model": model,
            "inputs": [{"content": [{"type": "image_base64", "image_base64": image["image"]}]}],
            **{k: body[k] for k in allowed if k in body},
        }
        try:
            async with ClientSession(timeout=ClientTimeout(total=120), trust_env=False) as session:
                async with session.post(VOYAGE_URL, json=payload, headers={"Authorization": auth}) as upstream:
                    result = await upstream.json(content_type=None)
                    if upstream.status != 200:
                        return web.json_response({"error": {"message": "Voyage 回應錯誤", "upstream_status": upstream.status}}, status=502)
        except Exception as exc:
            self.ctx.logger.warning("Voyage 圖片嵌入請求失敗: %s", type(exc).__name__)
            return web.json_response({"error": {"message": "Voyage 連線失敗"}}, status=502)
        try:
            vector = result["data"][0]["embedding"]
            if not isinstance(vector, list) or not vector or any(
                isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in vector
            ):
                raise ValueError("無效向量")
            usage = result.get("usage") or {}
            tokens = usage.get("total_tokens", 0)
            if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
                tokens = 0
        except (KeyError, IndexError, TypeError, ValueError):
            return web.json_response({"error": {"message": "Voyage 回應缺少有效向量"}}, status=502)
        encoded_vector = (
            base64.b64encode(struct.pack("<" + "f" * len(vector), *vector)).decode("ascii")
            if encoding == "base64" else vector
        )
        return web.json_response({"object": "list", "data": [{"object": "embedding", "index": 0, "embedding": encoded_vector}],
                                  "model": model, "usage": {"prompt_tokens": tokens, "total_tokens": tokens}})


def create_plugin() -> VoyageImageBridge:
    return VoyageImageBridge()
