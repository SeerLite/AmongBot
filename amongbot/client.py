import asyncio
import discord

from .botpresence import BotPresence


class Client(discord.Client):
    def __init__(self, *args, presences=[], save_data={}, **kwargs):
        super().__init__(*args, **kwargs)

        self.presences = presences
        self.save_data = save_data
        self.save_lock = asyncio.Lock()

    # Events
    async def on_ready(self):
        print(f"{self.user.name} is online!")
        for guild in self.guilds:
            if str(guild.id) in self.save_data:
                # TODO: is the stuff below pythonic? (appending and instantiating at the same time)
                self.presences.append(await BotPresence.create(
                    guild,
                    self,
                    text_channel_id=self.save_data[str(guild.id)]["text"],
                    voice_channel_id=self.save_data[str(guild.id)]["voice"],
                    control_panel_id=self.save_data[str(guild.id)]["control"],
                    excluded_roles_ids=self.save_data[str(guild.id)]["exclude"]
                ))
            else:
                self.presences.append(await BotPresence.create(
                    guild,
                    self
                ))

    async def on_guild_join(self, guild):
        self.presences.append(await BotPresence.create(
            guild
        ))

    async def on_guild_remove(self, guild):
        self.presences = [presence for presence in self.presences if presence.guild != guild]

    async def on_message(self, message):
        if message.author == self.user:
            return
        for presence in self.presences:
            await presence.on_message(message)  # NOTE: will receive messages from all guilds

    async def on_voice_state_update(self, member, before, after):
        if member == self.user:
            return
        for presence in self.presences:
            await presence.on_voice_state_update(member, before, after)  # NOTE: will receive updates from all guilds

    async def on_raw_reaction_add(self, payload):
        if payload.member == self.user:
            return
        for presence in self.presences:
            await presence.on_reaction_add(payload.emoji, payload.message_id, payload.member)  # NOTE: will receive reactions from all guilds
