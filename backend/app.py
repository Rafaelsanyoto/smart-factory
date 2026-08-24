"""Assembles the FastAPI application: CORS, routers, and the Discord bot startup hook.
Importing this module also triggers the import chain that starts the camera threads (they
idle while paused, which is the default on startup)."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import streams, settings, events, agent
from . import discord_bot

app = FastAPI(title="Smart Factory HSE API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(streams.router)
app.include_router(settings.router)
app.include_router(events.router)
app.include_router(agent.router)


@app.on_event("startup")
async def _launch_discord_bot():
    discord_bot.launch()
