import sys
import asyncio
import json
import base64
from pathlib import Path

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.agent.session_manager import VictorSessionManager
from app.agent.state import VictorState
from app.config import load_config
from app.logging import get_logger, setup_secure_logging

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE)
else:
    load_dotenv()

setup_secure_logging()
logger = get_logger("main")

_STATIC_DIR = _PROJECT_ROOT / "app" / "ui" / "static"

app = FastAPI(title="Victor 2.0 API")

@app.middleware("http")
async def add_cache_control_headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

@app.get("/")
async def root():
    return FileResponse(
        str(_STATIC_DIR / "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    # Callback to push server events down to the specific browser client
    async def ws_send(data: dict):
        try:
            await websocket.send_json(data)
        except Exception:
            pass

    # Each browser tab gets its own isolated session manager
    session_manager = VictorSessionManager(websocket_send_callback=ws_send)
    
    await ws_send({
        "type": "session_state",
        "state": session_manager.state.value
    })
    
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            msg_type = payload.get("type")
            
            if msg_type == "auth_request":
                success, message = await session_manager.authenticate(payload.get("credential", ""))
                await ws_send({"type": "auth_result", "success": success, "message": message})
                
            elif msg_type == "audio_input":
                if session_manager.state == VictorState.ACTIVE:
                    pcm_chunk = base64.b64decode(payload.get("data", ""))
                    await session_manager.handle_audio_input(pcm_chunk)
                    
            elif msg_type == "lock_request":
                await session_manager.lock()

    except WebSocketDisconnect:
        logger.info("Browser disconnected.")
        await session_manager.lock()


if __name__ == "__main__":
    import uvicorn

    config = load_config()
    uvicorn.run(
        "app.main:app",
        host=config.host,
        port=config.port,
        reload=False,
    )