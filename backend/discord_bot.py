"""Discord bot — two-way AI Agent chat directly from a Discord channel (read-only: it can
answer questions using the same tools, but can't execute actions — no confirm UI there).
Runs as a background asyncio task inside the SAME event loop FastAPI/uvicorn uses; launch()
is called from the app's startup event."""
import asyncio

from .config import DISCORD_BOT_TOKEN, DISCORD_CHAT_CHANNEL_ID
from .database import engine_lock, db_get_or_create_discord_session
from .agent import run_agent_chat_session_final

try:
    import discord as _discord
except ImportError:
    _discord = None

discord_bot_client = None

if _discord is not None and DISCORD_BOT_TOKEN:
    _discord.utils.setup_logging()  # discord.py logs via the `logging` module, not
                                     # print() — without a handler configured its own
                                     # connect/auth diagnostics are silently swallowed.
    _intents = _discord.Intents.default()
    _intents.message_content = True
    discord_bot_client = _discord.Client(intents=_intents)

    @discord_bot_client.event
    async def on_ready():
        print(f"[Discord Bot] Logged in as {discord_bot_client.user}")

    @discord_bot_client.event
    async def on_message(message):
        if message.author.bot:
            return
        if DISCORD_CHAT_CHANNEL_ID and str(message.channel.id) != str(DISCORD_CHAT_CHANNEL_ID):
            return
        question = message.content.strip()
        if not question:
            return

        with engine_lock:
            session_id = db_get_or_create_discord_session(message.channel.id)

        async with message.channel.typing():
            # run_agent_chat_session_final does blocking network calls (Gemini) — offload
            # to a thread so it doesn't stall the bot's event loop for other events. Using
            # a per-channel session gives the bot real multi-turn memory, unlike before.
            result = await asyncio.to_thread(run_agent_chat_session_final, session_id, question)

        reply = (result.get("reply") or "").strip() or "Maaf, tidak ada jawaban."
        if result.get("pending_action"):
            reply += (
                f"\n\n⚠️ Ini butuh konfirmasi aksi — buka dashboard AI Agent untuk menjalankannya: "
                f"{result['pending_action']['description']}"
            )
        await message.channel.send(reply[:1900])  # Discord message cap is 2000 chars

elif DISCORD_BOT_TOKEN and _discord is None:
    print("[Discord Bot] DISCORD_BOT_TOKEN is set but the 'discord.py' package isn't installed "
          "(pip install discord.py) — Discord chat is disabled.")


_discord_bot_task = None  # must keep a strong reference — asyncio only holds a weak one,
                          # an unreferenced task can be garbage-collected mid-flight


def launch():
    """Start the bot's gateway connection as a background task. Called from the FastAPI
    startup event so it runs inside the already-running event loop."""
    global _discord_bot_task
    if discord_bot_client is not None:
        _discord_bot_task = asyncio.create_task(discord_bot_client.start(DISCORD_BOT_TOKEN))
