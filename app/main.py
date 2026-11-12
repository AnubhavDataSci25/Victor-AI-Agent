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


def _collect_system_health() -> dict:
    """Collect real-time CPU, RAM, Disk, and Network metrics for the HUD."""
    import shutil
    import socket
    cpu_pct = 0.0
    ram_pct = 0
    ram_used_gb = 0.0
    ram_total_gb = 0.0
    disk_pct = 0
    network_online = False

    try:
        import ctypes
        import time as _time
        from ctypes import Structure, byref, c_ulong, c_ulonglong

        class MEMORYSTATUSEX(Structure):
            _fields_ = [
                ("dwLength", c_ulong),
                ("dwMemoryLoad", c_ulong),
                ("ullTotalPhys", c_ulonglong),
                ("ullAvailPhys", c_ulonglong),
                ("ullTotalPageFile", c_ulonglong),
                ("ullAvailPageFile", c_ulonglong),
                ("ullTotalVirtual", c_ulonglong),
                ("ullAvailVirtual", c_ulonglong),
                ("ullAvailExtendedVirtual", c_ulonglong),
            ]

        class FILETIME(Structure):
            _fields_ = [("dwLowDateTime", c_ulong), ("dwHighDateTime", c_ulong)]

        mem = MEMORYSTATUSEX()
        mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(byref(mem))
        ram_pct = int(mem.dwMemoryLoad)
        ram_total_gb = round(mem.ullTotalPhys / (1024 ** 3), 1)
        ram_used_gb = round((mem.ullTotalPhys - mem.ullAvailPhys) / (1024 ** 3), 1)

        def _read_cpu():
            idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
            ctypes.windll.kernel32.GetSystemTimes(byref(idle), byref(kernel), byref(user))
            return (
                (idle.dwHighDateTime << 32) | idle.dwLowDateTime,
                (kernel.dwHighDateTime << 32) | kernel.dwLowDateTime,
                (user.dwHighDateTime << 32) | user.dwLowDateTime,
            )

        i1, k1, u1 = _read_cpu()
        _time.sleep(0.08)
        i2, k2, u2 = _read_cpu()
        total_sys = (k2 - k1) + (u2 - u1)
        if total_sys > 0:
            cpu_pct = round(max(0.0, min(100.0, (total_sys - (i2 - i1)) * 100.0 / total_sys)), 1)
    except Exception:
        pass

    try:
        usage = shutil.disk_usage(str(_PROJECT_ROOT))
        if usage.total > 0:
            disk_pct = round((usage.used / usage.total) * 100)
    except Exception:
        pass

    try:
        socket.create_connection(("8.8.8.8", 53), timeout=1.0).close()
        network_online = True
    except Exception:
        network_online = False

    return {
        "cpu_pct": cpu_pct,
        "ram_pct": ram_pct,
        "ram_used_gb": ram_used_gb,
        "ram_total_gb": ram_total_gb,
        "disk_pct": disk_pct,
        "network_online": network_online,
        "model": "Gemini 3.8 Live",
    }


@app.get("/api/system-health")
async def get_system_health():
    return await asyncio.to_thread(_collect_system_health)

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

            elif msg_type == "audio_stream_end":
                if session_manager.state == VictorState.ACTIVE:
                    await session_manager.handle_audio_stream_end()

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