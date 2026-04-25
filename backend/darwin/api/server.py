"""FastAPI app + WebSocket bus. Person E owns.

Routes:
  GET  /api/health            liveness
  GET  /api/engines           list all engines
  GET  /api/generations       list all generations
  GET  /api/games?gen=N       games in a generation
  POST /api/generations/run   trigger a new generation
  WS   /ws                    live event stream
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from darwin.api.routes import router
from darwin.api.websocket import bus
from darwin.logging_setup import setup_logging
from darwin.storage.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_db()
    yield


app = FastAPI(title="Darwin", lifespan=lifespan)
app.include_router(router, prefix="/api")


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    q = bus.subscribe()
    try:
        while True:
            envelope = await q.get()
            await websocket.send_json(envelope)
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(q)
