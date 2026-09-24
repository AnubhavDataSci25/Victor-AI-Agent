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

from app.reminders.scheduler import get_global_reminder_scheduler

@app.on_event("startup")
async def startup_event():
    scheduler = get_global_reminder_scheduler()
    await scheduler.start()

@app.on_event("shutdown")
async def shutdown_event():
    scheduler = get_global_reminder_scheduler()
    await scheduler.stop()

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

from app.phone.server import get_local_ip, phone_server

@app.websocket("/ws/phone")
async def websocket_phone_endpoint(websocket: WebSocket):
    await phone_server.handle_websocket(websocket)


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
    
    # Connect phone server with active browser session
    phone_server.set_ui_notify_callback(ws_send)
    phone_server.gateway.set_session_manager(session_manager)

    # Connect persistent reminder scheduler with active browser session
    reminder_scheduler = get_global_reminder_scheduler()
    reminder_scheduler.set_session_auth_checker(session_manager.is_authenticated)

    async def dispatch_reminder(payload: dict):
        try:
            await ws_send(payload)
            if session_manager.is_authenticated():
                await ws_send({
                    "type": "transcript",
                    "role": "assistant",
                    "text": payload.get("message", ""),
                })
                await ws_send({
                    "type": "speak",
                    "text": payload.get("message", ""),
                })
        except Exception:
            pass

    reminder_scheduler.set_notification_dispatcher(dispatch_reminder)
    await reminder_scheduler.start()

    await ws_send({
        "type": "session_state",
        "state": session_manager.state.value
    })

    # Send initial phone companion status
    phone_status = phone_server.gateway.get_status()
    await ws_send({
        "type": "phone_status",
        **phone_status,
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
                if session_manager.state in (VictorState.ACTIVE, VictorState.BIOMETRIC_PENDING):
                    pcm_chunk = base64.b64decode(payload.get("data", ""))
                    await session_manager.handle_audio_input(pcm_chunk)

            elif msg_type == "user_command":
                cmd_text = payload.get("text", "")
                await session_manager.handle_command(cmd_text)

            elif msg_type == "biometric_request":
                await session_manager.trigger_biometric_verification()

            elif msg_type == "lock_request":
                await session_manager.lock()

            elif msg_type == "phone_pair_init":
                token, pin, expires_at = phone_server.device_manager.initiate_pairing()
                lan_ip = get_local_ip()
                config = load_config()
                await ws_send({
                    "type": "phone_pairing_data",
                    "ip": lan_ip,
                    "port": config.port,
                    "token": token,
                    "pin": pin,
                    "expires_at": expires_at,
                })

            elif msg_type == "phone_unpair":
                res = phone_server.gateway.unpair()
                await ws_send({
                    "type": "phone_status",
                    **phone_server.gateway.get_status(),
                })
                await ws_send({
                    "type": "transcript",
                    "role": "assistant",
                    "text": res.get("message", "Phone unpaired."),
                })

            elif msg_type == "phone_answer_call":
                res = await phone_server.gateway.answer_call()
                await ws_send({
                    "type": "transcript",
                    "role": "assistant",
                    "text": res.get("message", "Call answered."),
                })

            elif msg_type == "phone_reject_call":
                res = await phone_server.gateway.reject_call()
                await ws_send({
                    "type": "transcript",
                    "role": "assistant",
                    "text": res.get("message", "Call rejected."),
                })

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