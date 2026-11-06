from __future__ import annotations

import asyncio
import contextlib
import socket
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import BASE_DIR, settings
from .db import Base, engine
from .seed import seed
from .services.bus import bus
from .services.market import collect_fred_brent, collect_oil
from .services.scheduler import run_collect, shutdown_scheduler, start_scheduler
from .services.worker import worker_loop


async def _initial_collect() -> None:
    await asyncio.sleep(1.5)
    await asyncio.gather(
        collect_oil(),
        collect_fred_brent(),
        run_collect("jin10_flash"),
        run_collect("sina_rss"),
        run_collect("czce_announce"),
        return_exceptions=True,
    )
    await bus.publish("system", {"message": "initial collection finished"})


def _lan_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    seed()
    ok, msg = await settings.probe_llm()
    if ok:
        print(f"[radar] LLM 就绪：{settings.deepseek_model} · {msg}", flush=True)
    else:
        settings.llm_enabled = False
        print(f"[radar] LLM 不可用（{msg}），自动回退规则引擎。充值或更换 Key 后重启即可恢复。", flush=True)
    ip = _lan_ip()
    mode = "deepseek" if settings.llm_available else "rule"
    print(f"[radar] 模式：{mode}  ·  本机访问 http://127.0.0.1:{settings.port}  ·  局域网 http://{ip}:{settings.port}", flush=True)
    task = asyncio.create_task(worker_loop())
    start_scheduler()
    initial = asyncio.create_task(_initial_collect())
    yield
    initial.cancel()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    shutdown_scheduler()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)


# 下载端点（放在前端 mount 之前，避免被 SPA 路由吞掉）
@app.get("/download")
def download_project():
    zip_path = BASE_DIR / "static" / "downloads" / "futures-radar.zip"
    if zip_path.exists():
        return FileResponse(
            path=str(zip_path),
            filename="futures-radar.zip",
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=futures-radar.zip"},
        )
    return {"error": "压缩包未生成，请联系管理员"}


app.include_router(router)

dist = BASE_DIR.parent / "frontend" / "dist"
if dist.exists():
    app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")


@app.get("/")
def root():
    return {
        "app": settings.app_name,
        "message": "前端尚未构建：进入 frontend 目录执行 npm install && npm run build，或 npm run dev",
        "docs": "/docs",
    }
