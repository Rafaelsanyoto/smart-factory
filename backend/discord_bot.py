import asyncio
import os

from .config import DISCORD_BOT_TOKEN, DISCORD_CHAT_CHANNEL_ID
from .database import engine_lock, db_get_or_create_discord_session
from .agent import run_agent_chat_session_final, resolve_pending_action

try:
    import discord as _discord
except ImportError:
    _discord = None

discord_bot_client = None

if _discord is not None and DISCORD_BOT_TOKEN:
    _discord.utils.setup_logging()
    _intents = _discord.Intents.default()
    _intents.message_content = True
    discord_bot_client = _discord.Client(intents=_intents)

    @discord_bot_client.event
    async def on_ready():
        print(f"[Discord Bot] Logged in as {discord_bot_client.user}")

    class ConfirmActionView(_discord.ui.View):
        def __init__(self, message_id, description):
            super().__init__(timeout=300)
            self.message_id = message_id
            self.description = description

        async def _finish(self, interaction, approve):
            res = await asyncio.to_thread(resolve_pending_action, self.message_id, approve)
            for child in self.children:
                child.disabled = True
            icon = "✅" if res["ok"] and approve else ("🚫" if not approve else "⚠️")
            await interaction.response.edit_message(
                content=f"{icon} {self.description}\n> {res['message']}", view=self,
            )
            self.stop()

        @_discord.ui.button(label="Jalankan", style=_discord.ButtonStyle.success, emoji="✅")
        async def approve(self, interaction, button):
            await self._finish(interaction, True)

        @_discord.ui.button(label="Batal", style=_discord.ButtonStyle.secondary, emoji="❌")
        async def cancel(self, interaction, button):
            await self._finish(interaction, False)

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
            result = await asyncio.to_thread(run_agent_chat_session_final, session_id, question)

        reply = (result.get("reply") or "").strip() or "Maaf, tidak ada jawaban."
        pending = result.get("pending_action")

        files = []
        for r in (result.get("reports") or []):
            try:
                if os.path.exists(r["path"]):
                    files.append(_discord.File(r["path"], filename=r["filename"]))
            except Exception as e:
                print(f"[Discord Bot] attach report failed: {e}")

        if pending and result.get("agent_message_id"):
            desc = pending.get("description", "Aksi")
            view = ConfirmActionView(result["agent_message_id"], desc)
            await message.channel.send(f"{reply[:1700]}\n\n⚠️ **Konfirmasi aksi:** {desc}", view=view, files=files or None)
        else:
            await message.channel.send(reply[:1900], files=files or None)

elif DISCORD_BOT_TOKEN and _discord is None:
    print("[Discord Bot] DISCORD_BOT_TOKEN is set but the 'discord.py' package isn't installed "
          "(pip install discord.py) — Discord chat is disabled.")


_discord_bot_task = None  # keep a strong ref, asyncio only holds a weak one


def launch():
    global _discord_bot_task
    if discord_bot_client is not None:
        _discord_bot_task = asyncio.create_task(discord_bot_client.start(DISCORD_BOT_TOKEN))
