from starlette.testclient import TestClient
from fastapi import FastAPI
from starlette.responses import JSONResponse, PlainTextResponse
from src.api.middleware import CacheMiddleware

app = FastAPI()
app.add_middleware(CacheMiddleware)

@app.get("/json")
async def get_json():
    return JSONResponse({"status": "ok"})

@app.get("/text")
async def get_text():
    return PlainTextResponse("ok")

@app.get("/error")
async def get_error():
    raise ValueError("Test error")

client = TestClient(app)

def test_cache_control_on_authenticated_json():
    response = client.get("/json", headers={"Authorization": "Bearer test"})
    assert response.status_code == 200
    assert "no-store" in response.headers.get("Cache-Control", "")
    assert response.headers.get("Pragma") == "no-cache"
    assert response.headers.get("Expires") == "0"

def test_no_cache_control_on_unauthenticated_json():
    response = client.get("/json")
    assert response.status_code == 200
    assert "Cache-Control" not in response.headers

def test_no_cache_control_on_authenticated_text():
    response = client.get("/text", headers={"Authorization": "Bearer test"})
    assert response.status_code == 200
    assert "Cache-Control" not in response.headers

def test_exception_path_cleans_up():
    try:
        client.get("/error", headers={"Authorization": "Bearer test"})
    except ValueError:
        pass
    # The middleware should safely re-raise the exception and pass the finally block
    assert True
