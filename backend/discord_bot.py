"""Discord bot — two-way AI Agent chat directly from a Discord channel (read-only: it can
answer questions using the same tools, but can't execute actions — no confirm UI there).
Runs as a background asyncio task inside the SAME event loop FastAPI/uvicorn uses; launch()
is called from the app's startup event."""
import asyncio
import os

from .config import DISCORD_BOT_TOKEN, DISCORD_CHAT_CHANNEL_ID
from .database import engine_lock, db_get_or_create_discord_session
from .agent import run_agent_chat_session_final, resolve_pending_action
from . import followup

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

    # --- Incident follow-up: the reminder loop (followup.py) sends "belum ditindak"
    # messages through this sender so users can acknowledge with a ✅ / ❌ reaction. ------
    async def _async_send_incident(event, text):
        try:
            ch = discord_bot_client.get_channel(int(DISCORD_CHAT_CHANNEL_ID))
            if ch is None:
                ch = await discord_bot_client.fetch_channel(int(DISCORD_CHAT_CHANNEL_ID))
            msg = await ch.send(text)
            await msg.add_reaction("✅")
            await msg.add_reaction("❌")
            followup.register_incident_message(msg.id, event["id"])
        except Exception as e:
            print(f"[Discord Bot] send incident error: {e}")

    def _incident_sender(event, text):
        """Called from followup's worker thread — schedule the async send on the bot loop."""
        if not DISCORD_CHAT_CHANNEL_ID:
            return False
        loop = discord_bot_client.loop
        if loop is None or not loop.is_running():
            return False
        asyncio.run_coroutine_threadsafe(_async_send_incident(event, text), loop)
        return True

    followup.set_sender(_incident_sender)

    @discord_bot_client.event
    async def on_raw_reaction_add(payload):
        # Acknowledge an incident by reacting on the bot's reminder message.
        if discord_bot_client.user and payload.user_id == discord_bot_client.user.id:
            return
        event_id = followup.event_for_message(payload.message_id)
        if not event_id:
            return
        emoji = str(payload.emoji)
        who = f"<@{payload.user_id}>"
        if emoji == "✅":
            await asyncio.to_thread(followup.mark_acted, event_id, f"Ditindak (via Discord oleh {who})")
            ack = "✅ Insiden ditandai **sudah ditindak**."
        elif emoji == "❌":
            await asyncio.to_thread(followup.dismiss_with_feedback, event_id, "discord", f"Ditolak (via Discord oleh {who})")
            ack = "🚫 Insiden **dibatalkan** — dicatat sebagai feedback koreksi AI."
        else:
            return
        try:
            ch = discord_bot_client.get_channel(payload.channel_id) or await discord_bot_client.fetch_channel(payload.channel_id)
            msg = await ch.fetch_message(payload.message_id)
            await msg.reply(ack, mention_author=False)
        except Exception:
            pass

    class ConfirmActionView(_discord.ui.View):
        """Approve/Cancel buttons attached to a bot reply that proposed an action. Executes
        via the same resolve_pending_action() the web UI uses, so the outcome is persisted
        identically. Times out after 5 minutes."""
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
            # run_agent_chat_session_final does blocking network calls (Gemini) — offload
            # to a thread so it doesn't stall the bot's event loop for other events. Using
            # a per-channel session gives the bot real multi-turn memory, unlike before.
            result = await asyncio.to_thread(run_agent_chat_session_final, session_id, question)

        reply = (result.get("reply") or "").strip() or "Maaf, tidak ada jawaban."
        pending = result.get("pending_action")

        # Attach any report files generated this turn as real downloadable attachments.
        files = []
        for r in (result.get("reports") or []):
            try:
                if os.path.exists(r["path"]):
                    files.append(_discord.File(r["path"], filename=r["filename"]))
            except Exception as e:
                print(f"[Discord Bot] attach report failed: {e}")

        # An action reaches here (still pending) only when the permission mode requires a
        # human to confirm it — auto / accept-low-risk actions already ran inline. Offer the
        # confirm buttons right in Discord instead of forcing a trip to the dashboard.
        if pending and result.get("agent_message_id"):
            desc = pending.get("description", "Aksi")
            view = ConfirmActionView(result["agent_message_id"], desc)
            await message.channel.send(f"{reply[:1700]}\n\n⚠️ **Konfirmasi aksi:** {desc}", view=view, files=files or None)
        else:
            await message.channel.send(reply[:1900], files=files or None)

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
