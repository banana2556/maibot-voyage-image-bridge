import asyncio
import importlib.util
from pathlib import Path

from aiohttp import ClientSession, web
from openai import AsyncOpenAI
import pytest


@pytest.fixture
def plugin_module():
    spec = importlib.util.spec_from_file_location("voyage_bridge", Path(__file__).resolve().parents[1] / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_translation_and_rejections(plugin_module, monkeypatch):
    asyncio.run(_translation_and_rejections(plugin_module, monkeypatch))


async def _translation_and_rejections(plugin_module, monkeypatch):
    received = []

    async def upstream(request):
        received.append((request.headers.get("Authorization"), await request.json()))
        return web.json_response({"data": [{"embedding": [0.2, 0.8]}], "usage": {"total_tokens": 7}})

    app = web.Application()
    app.router.add_post("/upstream", upstream)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    monkeypatch.setattr(plugin_module, "VOYAGE_URL", f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/upstream")
    bridge = plugin_module.VoyageImageBridge()
    bridge.set_plugin_config({})
    bridge._plugin_config_instance.__dict__["port"] = 0  # 測試隔離：作業系統分配臨時埠
    bridge._ctx = type("Ctx", (), {"logger": type("Log", (), {"info": lambda *a: None, "warning": lambda *a: None})()})()
    await bridge.on_load()
    port = bridge._site._server.sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}/v1/embeddings"
    try:
        async with ClientSession() as client:
            body = {"model": "voyage-multimodal-3.5", "input": {"image": "data:image/png;base64,aGVsbG8="}}
            async with client.post(base, json=body, headers={"Authorization": "Bearer dummy"}) as response:
                assert response.status == 200
                result = await response.json()
                assert result["data"][0]["embedding"] == [0.2, 0.8]
                assert result["usage"]["total_tokens"] == 7
            assert received == [("Bearer dummy", {"model": body["model"], "inputs": [{"content": [{"type": "image_base64", "image_base64": body["input"]["image"]}]}]})]
            async with AsyncOpenAI(base_url=f"http://127.0.0.1:{port}/v1", api_key="dummy") as sdk:
                response = await sdk.embeddings.create(model=body["model"], input=body["input"])
                assert response.data[0].embedding == pytest.approx([0.2, 0.8])
            assert len(received) == 2
            async with client.post(base, json=body) as response:
                assert response.status == 401
            async with client.post(base, json={**body, "model": "other"}, headers={"Authorization": "Bearer dummy"}) as response:
                assert response.status == 400
            async with client.post(base, json={**body, "input": {"image": "https://example.com/private"}}, headers={"Authorization": "Bearer dummy"}) as response:
                assert response.status == 400
            assert len(received) == 2
    finally:
        await bridge.on_unload()
        await runner.cleanup()
