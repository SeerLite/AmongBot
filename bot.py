import os
import sys
import asyncio
import json
import discord

if not (TOKEN := os.getenv("DISCORD_TOKEN")):
    try:
        with open(".token") as token_file:
            TOKEN = token_file.read()
    except FileNotFoundError:
        print("No .token file found! Please create it or pass it through DISCORD_TOKEN environment variable.")
        sys.exit(1)

client = discord.Client()


class Error(Exception):
    """Base class for exceptions in amongbot"""
    pass


class SameValueError(Error):
    def __init__(self, msg=None):
        self.msg = msg

    def __str__(self):
        return self.msg


class TrackedMember:
    def __init__(self, member, presence, *, list=True, dead=False, mute=False, ignore=False):
        self.member = member
        self.presence = presence
        self.list = list
        self.dead = dead
        self.mute = mute
        self.ignore = ignore
        self.mute_lock = asyncio.Lock()

    async def set_mute(self, mute_state, *, only_listed=True):
        async with self.mute_lock:
            if not self.ignore and (self.list or not only_listed) and self.member.voice and self.member.voice.channel == self.presence.voice_channel:
                if self.dead and not self.member.voice.mute:
                    await self.member.edit(mute=True)
                    self.mute = True
                elif self.member.voice.mute != mute_state:
                    await self.member.edit(mute=mute_state)
                    self.mute = mute_state


class BotPresence:
    @classmethod
    async def create(cls, guild, *, text_channel_id=None, voice_channel_id=None, control_panel_id=None, excluded_roles_ids=[]):
        self = BotPresence()

        self.guild = guild

        if text_channel_id:
            self._text_channel = self.guild.get_channel(int(text_channel_id))
        else:
            self._text_channel = None

        if voice_channel_id:
            self._voice_channel = self.guild.get_channel(int(voice_channel_id))
        else:
            self._voice_channel = None

        if control_panel_id:
            # TODO: fetch_message() can raise exceptions, handle them
            self.control_panel = await self.text_channel.fetch_message(int(control_panel_id))
        else:
            self.control_panel = None

        self._excluded_roles = frozenset(self.guild.get_role(int(id)) for id in excluded_roles_ids)  # frozen cause we're only assigning anyway
        self._muting = False
        self.muting_lock = asyncio.Lock()
        self.mimic = None
        self.tracked_members = []

        if self.text_channel and self.voice_channel:
            await self.track_current_voice()

        if self.control_panel:
            await self.update_control_panel()

        self.save()
        return self

    @property
    def text_channel(self):
        return self._text_channel

    @text_channel.setter
    def text_channel(self, channel):
        # TODO: check for permissions in channel here. message user personally if can't send to channel
        if self._text_channel == channel:
            raise SameValueError
        self._text_channel = channel
        self.save()

    @property
    def voice_channel(self):
        return self._voice_channel

    @voice_channel.setter
    def voice_channel(self, channel):
        if self._voice_channel == channel:
            raise SameValueError
        # TODO: check for permissions in vc here
        self._voice_channel = channel
        self.save()

    @property
    def excluded_roles(self):
        return self._excluded_roles

    async def set_excluded_roles(self, excluded_roles):
        if self._excluded_roles == excluded_roles:
            raise SameValueError
        if new_excludes := excluded_roles.difference(self._excluded_roles):  # only if there's _new_ roles
            # unmute and untrack all members from newly excluded role
            await asyncio.gather(*(tracked_member.set_mute(False) for tracked_member in self.tracked_members if any((role in new_excludes for role in tracked_member.member.roles))))
            self.tracked_members = [tracked_member for tracked_member in self.tracked_members if not any((role in new_excludes for role in tracked_member.member.roles))]
        elif new_unexcludes := self._excluded_roles.union(excluded_roles):  # only if there's _less_ roles
            # track and mute newly unexcluded roles
            for member in self.voice_channel.members:
                if any(role in new_unexcludes for role in member.roles):
                    self.tracked_members.append(TrackedMember(member, self))
            await asyncio.gather(*(tracked_member.set_mute(self.muting) for tracked_member in self.tracked_members if any((role in new_unexcludes for role in tracked_member.member.roles))))
        self._excluded_roles = excluded_roles
        self.save()

    @property
    def muting(self):
        return self._muting

    async def set_muting(self, mute_state, *, only_listed=True):
        with self.muting_lock:
            self._muting = mute_state
            await asyncio.gather(*(tracked_member.set_mute(mute_state) for tracked_member in self.tracked_members))

    def save(self):
        if not str(self.guild.id) in save_data:
            save_data[str(self.guild.id)] = {}
        for name, value in (("text", self.text_channel), ("voice", self.voice_channel), ("control", self.control_panel)):
            if value:
                save_data[str(self.guild.id)][name] = value.id
            else:
                save_data[str(self.guild.id)][name] = None

        save_data[str(self.guild.id)]["exclude"] = [role.id for role in self.excluded_roles]

        try:
            with open("data.json", "w") as save_file:
                json.dump(save_data, save_file)
        except FileNotFoundError:
            with open("data.json", "x") as save_file:
                json.dump(save_data, save_file)

    async def track_current_voice(self):
        await self.set_muting(False, only_listed=False)
        self.tracked_members = [TrackedMember(member, self, ignore=True if member.voice.mute != self.muting else False) for member in self.voice_channel.members if not any((role in self.excluded_roles for role in member.roles))]

    # TODO: maybe it's a good idea to use ext.commands instead of manually doing the stuff
    async def on_message(self, message):
        if message.guild != self.guild:
            return
        if message.content == "among:setup":  # TODO: make this a method?
            # TODO: make this logic cleaner in some way (idk how rn)
            try:
                self.text_channel = message.channel
            except SameValueError:
                pass

            try:
                if message.author.voice:
                    self.voice_channel = message.author.voice.channel
                    await self.track_current_voice()
                else:
                    self.voice_channel = None
                await self.text_channel.send(f"All good! Listening for commands only on {self.text_channel.mention} and tracking {self.voice_channel.name}.")
                await self.send_control_panel()
            except SameValueError:
                if self.voice_channel:
                    await self.text_channel.send(f"Already set up! This is {client.user.display_name}'s channel and currently tracking {self.voice_channel.name}.")
                else:
                    await self.text_channel.send(f"Error! User {message.author.mention} not in any voice channel on this server! Please join a voice channel first!")
                    self.text_channel = None
        elif message.content == "among:text":
            try:
                self.text_channel = message.channel
                await self.text_channel.send(f"Current channel {self.text_channel.mention} set as {client.user.name}'s channel!\n"
                                             f"Now accepting commands here.")
                if self.voice_channel:
                    await self.send_control_panel()
            except SameValueError:
                await self.text_channel.send(f"Error! This channel is already {client.user.name}'s channel.")
        elif message.channel == self.text_channel:
            if message.content == "among:vc":
                try:
                    if message.author.voice:
                        self.voice_channel = message.author.voice.channel
                        await self.track_current_voice()
                        await self.text_channel.send(f"{self.voice_channel.name} set as tracked voice channel!")
                        await self.send_control_panel()
                    else:
                        self.voice_channel = None
                        if self.control_panel:
                            await self.control_panel.delete()
                            self.control_panel = None
                            self.save()
                        await self.text_channel.send(f"User {message.author.mention} not in any voice channel on this server. Stopped tracking voice channel.")
                except SameValueError:
                    if self.voice_channel:
                        await self.text_channel.send(f"Error! {self.voice_channel.name} is already tracked. To untrack, run `among:vc` while not connected to any channel.")
                    else:
                        await self.text_channel.send(f"Error! User {message.author.mention} not in any voice channel on this server! Please join a voice channel first!")
            # TODO: DRY this (but how?)
            elif message.content.startswith("among:excluderole"):
                if message.role_mentions:
                    try:
                        await self.set_excluded_roles(self.excluded_roles.union(message.role_mentions))
                        await self.text_channel.send(f"Now excluding roles:\n{' '.join((role.mention for role in self.excluded_roles))}")
                        await self.update_control_panel()
                    except SameValueError:
                        await self.text_channel.send("Error! All mentioned roles were already excluded.")
                else:
                    await self.text_channel.send("Error! No role mentions detected!\nUsage: `among:excluderole <role mention>...`")
            elif message.content.startswith("among:unexcluderole"):
                if message.role_mentions:
                    try:
                        await self.set_excluded_roles(self.excluded_roles.difference(message.role_mentions))
                        if self.excluded_roles:
                            await self.text_channel.send(f"Now excluding roles:\n{' '.join((role.mention for role in self.excluded_roles))}")
                        else:
                            await self.text_channel.send("No longer excluding any roles.")
                        await self.update_control_panel()
                    except SameValueError:
                        await self.text_channel.send("Error! None of the mentioned roles were excluded.")
                else:
                    await self.text_channel.send("Error! No role mentions detected!\nUsage: `among:excluderole <role mention>...`")
            elif message.content.isdigit() or (message.content[0] == "-" and message.content[1:].isdigit()):
                index = abs(int(message.content)) - 1
                if index in range(len(self.tracked_members)):
                    await message.delete()
                    if int(message.content) > 0:
                        if not self.tracked_members[index].ignore:
                            self.tracked_members[index].dead = not self.tracked_members[index].dead
                    else:  # if index is negative, toggle ignore instead of dead
                        self.tracked_members[index].ignore = not self.tracked_members[index].ignore
                    await self.set_muting(self.muting)
                    await self.update_control_panel()

    async def send_control_panel(self):
        if self.control_panel:
            await self.control_panel.delete()
        self.control_panel = await self.text_channel.send("```\n```")
        self.save()
        await self.control_panel.add_reaction('🔈')
        await self.control_panel.add_reaction('©')
        await self.control_panel.add_reaction('🔄')
        await self.update_control_panel()

    async def update_control_panel(self):
        if self.control_panel is None:
            return
        control_panel_text = (
            f"**Muting:** {'Yes' if self.muting else 'No'}\n"
            f"**Tracked users:**\n"
            "```\n"
        )
        # TODO
        for tracked_member in (tracked_member for tracked_member in self.tracked_members if tracked_member.list):
            # TODO: make this line shorter
            control_panel_text += f"{self.tracked_members.index(tracked_member) + 1}. {'(IGNORED)' if tracked_member.ignore else ' (DEAD)  ' if tracked_member.dead else ' (MUTED) ' if tracked_member.mute else ' (ALIVE) '} {tracked_member.member.display_name.ljust(max((len(tracked_member.member.display_name) for tracked_member in self.tracked_members)))} | {tracked_member.member.name}#{tracked_member.member.discriminator}\n"
        control_panel_text += "```"
        if self.mimic:
            control_panel_text += f"**Mimicking:** {self.mimic.mention}"
        else:
            control_panel_text += "Not mimicking! React with :copyright: to mimic you!"
        await self.control_panel.edit(content=control_panel_text)

    async def set_mimic(self, member):
        if member:
            if member.voice and member.voice.channel == self.voice_channel:
                self.mimic = member
                await self.set_muting(self.muting)  # TODO: maybe set_muting() with no args should default to current mute
                return True
            else:
                return False
        else:
            self.mimic = None

    async def on_voice_state_update(self, member, before, after):
        if member.guild != self.guild:
            return
        if self.voice_channel is None:
            return
        if any((role in self.excluded_roles for role in member.roles)):
            return
        if member == self.mimic:
            if after.channel == self.voice_channel:  # Status changed inside channel
                if before.self_deaf != after.self_deaf:
                    await self.set_muting(after.self_deaf)
                    await self.update_control_panel()
            else:                                # Whoops, not in channel anymore?
                await self.set_mimic(None)
                await self.update_control_panel()
        if before.channel != after.channel:
            if after.channel == self.voice_channel:
                if member not in (tracked_member.member for tracked_member in self.tracked_members):
                    self.tracked_members.append(TrackedMember(member, self, ignore=True if member.voice.mute != self.muting else False))  # ignore new members that don't match current mute state
                    await self.update_control_panel()
                else:
                    for tracked_member in self.tracked_members:
                        if member == tracked_member.member and not tracked_member.list:
                            tracked_member.list = True
                            await self.update_control_panel()
            elif after.channel != self.voice_channel:
                if member in (tracked_member.member for tracked_member in self.tracked_members):  # stop listing tracked_members who leave (but don't stop tracking them unless there's no more tracked members!)
                    for tracked_member in self.tracked_members:
                        if member == tracked_member.member and tracked_member.list and (not tracked_member.mute or tracked_member.ignore):
                            tracked_member.list = False

                if not any((tracked_member.list for tracked_member in self.tracked_members)):  # reset indexes when managed members leave
                    await self.set_muting(False, only_listed=False)
                    self.tracked_members = []
                await self.update_control_panel()

    async def on_reaction_add(self, emoji, message_id, member):
        if member.guild != self.guild:
            return
        if self.control_panel is None:
            return
        if message_id == self.control_panel.id:  # TODO: why doesn't this work without .id?
            if emoji.name == '🔈':
                await self.set_muting(not self.muting)
                await self.update_control_panel()
            elif emoji.name == '©':
                if self.mimic is None:
                    await self.set_mimic(member)
                    await self.update_control_panel()
                elif member == self.mimic:
                    await self.set_mimic(None)
                    await self.update_control_panel()
            elif emoji.name == '🔄':
                for tracked_member in self.tracked_members:
                    tracked_member.dead = False
                await self.set_muting(False)
                await self.update_control_panel()
            else:
                print(repr(emoji))
            # TODO: fetch_message() exception handling (idk if it matters in here tho)
            message = await self.text_channel.fetch_message(message_id)
            await message.remove_reaction(emoji, member)


@client.event
async def on_ready():
    print("Bot is online.")
    client.presences = []
    for guild in client.guilds:
        if str(guild.id) in save_data:
            client.presences.append(await BotPresence.create(
                guild,
                text_channel_id=save_data[str(guild.id)]["text"],
                voice_channel_id=save_data[str(guild.id)]["voice"],
                control_panel_id=save_data[str(guild.id)]["control"],
                excluded_roles_ids=save_data[str(guild.id)]["exclude"],
            ))
        else:
            client.presences.append(await BotPresence.create(
                guild
            ))


@client.event
async def on_guild_join(guild):
    client.presences.append(await BotPresence.create(
        guild
    ))


@client.event
async def on_guild_remove(guild):
    client.presences = [presence for presence in client.presences if presence.guild != guild]


@client.event
async def on_message(message):
    if message.author == client.user:
        return
    for presence in client.presences:
        await presence.on_message(message)  # NOTE: will receive messages from all guilds


@client.event
async def on_voice_state_update(member, before, after):
    if member == client.user:
        return
    for presence in client.presences:
        await presence.on_voice_state_update(member, before, after)  # NOTE: will receive updates from all guilds


@client.event
async def on_raw_reaction_add(payload):
    if payload.member == client.user:
        return
    for presence in client.presences:
        await presence.on_reaction_add(payload.emoji, payload.message_id, payload.member)  # NOTE: will receive reactions from all guilds

if __name__ == '__main__':
    try:
        with open("data.json") as save_file:
            save_data = json.load(save_file)
    except FileNotFoundError:
        save_data = {}
    client.run(TOKEN)
