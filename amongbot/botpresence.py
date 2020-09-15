import asyncio
import json
import discord
import timeit

from .errors import SameValueError
from .constants import SOURCE_CODE_URL


class TrackedMember:
    def __init__(self, member, presence, *, dead=False, mute=False, ignore=False):
        self.member = member
        self.presence = presence
        self.state = "alive"
        self._mute = mute
        self.mute_lock = asyncio.Lock()

    @property
    def mute(self):
        return self._mute

    async def set_mute(self, mute_state):
        async with self.mute_lock:
            if self.state != "ignored" and self.is_in_vc:
                if self.state == "dead":
                    self._mute = True
                else:
                    self._mute = mute_state
                if self.member.voice.mute != self._mute:
                    await self.member.edit(mute=self._mute)

    # TODO: i think this is dumb, should probably remove it or make it a function()()()()
    @property
    def is_in_vc(self):
        if self.member.voice and self.member.voice.channel == self.presence.voice_channel:
            return True
        else:
            return False


class ControlPanel:
    def __init__(self, presence, message=None):
        self.presence = presence
        self.message = message

    @classmethod
    async def from_id(cls, id, presence):
        self = ControlPanel(presence)
        self.message = await presence.text_channel.fetch_message(id)  # NOTE: handle exceptions externally

        await self.reset_reactions()
        await self.update()

        return self

    async def send_new(self):
        if self.message:
            await self.message.delete()

        self.message = await self.presence.text_channel.send("Loading...")
        await self.presence.save()
        await self.reset_reactions()
        await self.update()

    async def reset_reactions(self):
        await self.message.clear_reactions()
        await self.message.add_reaction('🔈')
        await self.message.add_reaction('©')
        await self.message.add_reaction('🔄')

    async def update(self):
        if self.message is None:
            return

        # TODO: maybe move this to another file, somehow? also, allowing different languages would be cool
        text = (
            f"**Muting:** `{'Yes' if self.presence.muting else 'No'}`\n"
            f"**Tracked users:**\n"
        )
        for tracked_member in self.presence.tracked_members:
            text += (f"`{' --' if not tracked_member.is_in_vc else str(self.presence.tracked_members.index(tracked_member) + 1).rjust(3)}. "
                     f"{tracked_member.member.display_name.ljust(max(len(tracked_member.member.display_name) for tracked_member in self.presence.tracked_members))} "
                     f"{ ('(' + tracked_member.state.upper() + ')').rjust(9)}` "
                     f"{tracked_member.member.mention}\n")

        if self.presence.mimic:
            text += f"**Mimicking:** {self.presence.mimic.mention}. Quickly deafen and undeafen yourself to toggle global mute.\n"
        else:
            text += "Not mimicking! React with :copyright: to mimic you!\n"

        text += ("Send the index of a member to set them as dead/alive (e.g `1`). React with :arrows_counterclockwise: to reset dead members.\n"
                 "Send the index of a member with a dash prepended to ignore/unignore them (e.g `-1`). New members are ignored by default.")

        await self.message.edit(content=text)

class BotPresence:
    @classmethod
    async def create(cls, guild, client, *, text_channel_id=None, voice_channel_id=None, control_panel_id=None, excluded_roles_ids=[]):
        self = BotPresence()

        self.guild = guild
        self.client = client
        self._text_channel = None
        self._voice_channel = None
        self.control_panel = ControlPanel(self)

        if text_channel_id:
            self._text_channel = self.guild.get_channel(int(text_channel_id))
        if voice_channel_id:
            self._voice_channel = self.guild.get_channel(int(voice_channel_id))

        self._excluded_roles = frozenset(self.guild.get_role(int(id)) for id in excluded_roles_ids)  # frozen cause we're only assigning anyway
        self._muting = False
        self.muting_lock = asyncio.Lock()
        self.mimic_undeafen_timeout = 1
        self.mimic_deafen_time = timeit.default_timer() - self.mimic_undeafen_timeout  # Used to detect if mimicked user was muted and unmuted in same second
        self.mute_delay = 5  # TODO: Make this scale with the amount of members in the voice channel (0.5s for each member)
        self.last_mute_time = timeit.default_timer() - self.mute_delay
        self.mimic = None
        self.tracked_members = []

        if self.text_channel and self.voice_channel:
            await self.track_current_voice()

            if control_panel_id:
                try:
                    self.control_panel.message = await self.text_channel.fetch_message(int(control_panel_id))
                    await self.control_panel.reset_reactions()
                    await self.control_panel.update()
                except discord.HTTPException:
                    pass

        if self.control_panel.message:
            await self.control_panel.update()

        await self.save()
        return self

    @property
    def text_channel(self):
        return self._text_channel

    async def set_text_channel(self, channel):
        # TODO: check for permissions in channel here. message user personally if can't send to channel
        if self._text_channel == channel:
            raise SameValueError(channel)
        self._text_channel = channel
        await self.save()

    @property
    def voice_channel(self):
        return self._voice_channel

    async def set_voice_channel(self, channel):
        if self._voice_channel == channel:
            raise SameValueError(channel)
        # TODO: check for permissions in vc here
        self._voice_channel = channel
        await self.save()

    @property
    def excluded_roles(self):
        return self._excluded_roles

    async def set_excluded_roles(self, excluded_roles):
        if self._excluded_roles == excluded_roles:
            raise SameValueError(excluded_roles)

        if excluded_roles.difference(self._excluded_roles):  # only if there's _new_ roles
            new_excludes = excluded_roles.difference(self._excluded_roles)
            # unmute and untrack all members from newly excluded role
            await asyncio.gather(*(tracked_member.set_mute(False) for tracked_member in self.tracked_members if any((role in new_excludes for role in tracked_member.member.roles))))  # TODO: maybe make a function/method for the generator here?
            self.tracked_members = [tracked_member for tracked_member in self.tracked_members if not any((role in new_excludes for role in tracked_member.member.roles))]
        elif self._excluded_roles.union(excluded_roles):  # only if there's _less_ roles
            new_unexcludes = self._excluded_roles.union(excluded_roles)
            # track and mute newly unexcluded roles
            for member in self.voice_channel.members:
                if any(role in new_unexcludes for role in member.roles):
                    self.tracked_members.append(TrackedMember(member, self))
            await asyncio.gather(*(tracked_member.set_mute(self.muting) for tracked_member in self.tracked_members if any((role in new_unexcludes for role in tracked_member.member.roles))))
        self._excluded_roles = excluded_roles
        await self.save()

    @property
    def muting(self):
        return self._muting

    # TODO: rename this method to mute_all or something?
    async def set_muting(self, mute_state):
        async with self.muting_lock:
            self._muting = mute_state
            await asyncio.gather(*(tracked_member.set_mute(mute_state) for tracked_member in self.tracked_members))

    async def save(self):
        async with self.client.save_lock:
            if not str(self.guild.id) in self.client.save_data:
                self.client.save_data[str(self.guild.id)] = {}

            for name, value in (("text", self.text_channel), ("voice", self.voice_channel), ("control", self.control_panel.message)):
                if value:
                    self.client.save_data[str(self.guild.id)][name] = value.id
                else:
                    self.client.save_data[str(self.guild.id)][name] = None
            self.client.save_data[str(self.guild.id)]["exclude"] = [role.id for role in self.excluded_roles]

            try:
                with open("data.json", "w") as save_file:
                    json.dump(self.client.save_data, save_file)
            except FileNotFoundError:
                with open("data.json", "x") as save_file:
                    json.dump(self.client.save_data, save_file)

    async def track_current_voice(self):
        await self.set_muting(False)
        self.tracked_members = [TrackedMember(member, self, ignore=True if member.voice.mute != self.muting else False) for member in self.voice_channel.members if not any((role in self.excluded_roles for role in member.roles))]

    # TODO: maybe it's a good idea to use ext.commands instead of manually doing this stuff
    async def on_message(self, message):
        if message.guild != self.guild:
            return
        if message.content == "among:help":
            response = ("**Quick start**\n"
                        "```markdown\n"
                        f"1. Create a dedicated text channel for {self.client.user.name}.\n"
                        "2. Join the voice channel you want to track.\n"
                        "3. Type among:setup in the dedicated text channel.\n"
                        "```\n"
                        "**Global commands**\n"
                        "```yaml\n"
                        "among:help : Sends this help text.\n"
                        "among:setup : Runs among:text and among:vc\n"
                        "among:text : Sets the current channel as the dedicated text channel.\n"
                        "```\n"
                        "**Commands for dedicated text channel**\n"
                        "```yaml\n"
                        "among:vc : Sets the current voice channel as the tracked channel.\n"
                        "among:excluderole : Exclude mentioned roles from muting.\n"
                        "among:unexcluderole  : Stop excluding mentioned roles.\n"
                        "```\n"
                        f"This bot is Free Software. Get the source code from here: {SOURCE_CODE_URL}\n")
            await message.channel.send(response)
        elif message.content == "among:setup":  # TODO: make this a method?
            # TODO: DRY this
            if message.author.voice:
                try:
                    await self.set_text_channel(message.channel)
                    await self.set_voice_channel(message.author.voice.channel)
                    await self.track_current_voice()
                    await self.text_channel.send(f"All good! Listening for commands only on {self.text_channel.mention} and tracking {self.voice_channel.name}.")
                    await self.control_panel.send_new()
                except SameValueError as error:
                    if error.args[0] == message.channel:
                        try:
                            await self.set_voice_channel(message.author.voice.channel)
                            await self.track_current_voice()
                            await self.text_channel.send(f"All good! Listening for commands only on {self.text_channel.mention} and tracking {self.voice_channel.name}.")
                            await self.control_panel.send_new()
                        except SameValueError as error:
                            if error.args[0] == message.author.voice.channel:
                                await self.text_channel.send(f"Already set up! This is {self.client.user.name}'s channel and currently tracking {self.voice_channel.name}.")
                    elif error.args[0] == message.author.voice.channel:
                        await self.text_channel.send(f"All good! Listening for commands only on {self.text_channel.mention} and tracking {self.voice_channel.name}.")
                        await self.control_panel.send_new()
            else:
                await message.channel.send(f"Error! User {message.author.mention} not in any voice channel on this server! Please join a voice channel first!")
        elif message.content == "among:text":
            try:
                await self.set_text_channel(message.channel)
                await self.text_channel.send(f"Current channel {self.text_channel.mention} set as {self.client.user.name}'s channel!\n"
                                             f"Now accepting commands here.")
                if self.voice_channel:
                    await self.control_panel.send_new()
            except SameValueError:
                await self.text_channel.send(f"Error! This channel is already {self.client.user.name}'s channel.")
        elif message.channel == self.text_channel:
            if message.content == "among:vc":
                try:
                    if message.author.voice:
                        await self.set_voice_channel(message.author.voice.channel)
                        await self.track_current_voice()
                        await self.text_channel.send(f"{self.voice_channel.name} set as tracked voice channel!")
                        await self.control_panel.send_new()
                    else:
                        await self.set_voice_channel(None)
                        if self.control_panel.message:
                            await self.control_panel.message.delete()
                            self.control_panel.message = None
                            await self.save()
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
                        await self.control_panel.update()
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
                        await self.control_panel.update()
                    except SameValueError:
                        await self.text_channel.send("Error! None of the mentioned roles were excluded.")
                else:
                    await self.text_channel.send("Error! No role mentions detected!\nUsage: `among:excluderole <role mention>...`")
            elif all(received_index.isdigit() or (received_index and received_index[0] == "-" and received_index[1:].isdigit()) for received_index in message.content.split(" ")):
                for received_index in set(message.content.split(" ")):
                    index = abs(int(received_index)) - 1
                    if index in range(len(self.tracked_members)):
                        if received_index[0] == "-":  # toggle ignored
                            if self.tracked_members[index].state == "ignored":
                                self.tracked_members[index].state = "alive"
                            else:
                                self.tracked_members[index].state = "ignored"
                        else:                   # toggle dead
                            if self.tracked_members[index].state == "alive":
                                self.tracked_members[index].state = "dead"
                            elif self.tracked_members[index].state == "dead":
                                self.tracked_members[index].state = "alive"
                await self.set_muting(self.muting)
                await self.control_panel.update()
                await message.delete()

    async def set_mimic(self, member):
        if member:
            if member.voice and member.voice.channel == self.voice_channel:
                self.mimic = member
                await self.set_muting(self.muting)  # TODO: maybe set_muting() with no args should default to current mute (or maybe set_muting shouldn't do all it does? (or maybe it should be renamed??))
                return True  # Remove return values and use exceptions?
            else:
                return False
        else:
            self.mimic = None

    async def on_voice_state_update(self, member, before, after):
        if member.guild != self.guild or self.voice_channel is None or any((role in self.excluded_roles for role in member.roles)):
            return

        muting_in_progress = self.muting_lock.locked()

        if member == self.mimic:
            if after.channel == self.voice_channel:  # Status changed inside channel
                if not before.self_deaf and after.self_deaf:    # Deafened
                    self.mimic_deafen_time = timeit.default_timer()
                elif before.self_deaf and not after.self_deaf:  # Undeafened
                    if (timeit.default_timer() - self.mimic_deafen_time) < self.mimic_undeafen_timeout:
                        if (timeit.default_timer() - self.last_mute_time) > self.mute_delay:
                            await self.set_muting(not self.muting)
                            await self.control_panel.update()
                            self.last_mute_time = timeit.default_timer()
            else:                                    # Whoops, not in channel anymore?
                await self.set_mimic(None)
                await self.control_panel.update()

        if before.channel != after.channel:
            if after.channel == self.voice_channel:
                if member not in (tracked_member.member for tracked_member in self.tracked_members):
                    self.tracked_members.append(TrackedMember(member, self, ignore=True if member.voice.mute != self.muting else False))  # ignore new members that don't match current mute state
                await self.control_panel.update()
            elif after.channel != self.voice_channel:
                if not any((tracked_member.is_in_vc for tracked_member in self.tracked_members)):  # reset indexes when all managed members leave
                    await self.set_muting(False)
                    self.tracked_members = []
                await self.control_panel.update()

        if before.mute != after.mute and not muting_in_progress and after.channel == self.voice_channel:
            for tracked_member in self.tracked_members:
                if member == tracked_member.member:
                    tracked_member.state = "ignored"
                    await self.control_panel.update()
                    break

    async def on_reaction_add(self, emoji, message_id, member):
        if member.guild != self.guild or self.control_panel.message is None:
            return
        if message_id == self.control_panel.message.id:  # TODO: why doesn't this work without .id?
            if emoji.name == '🔈':
                if (timeit.default_timer() - self.last_mute_time) > self.mute_delay:  # TODO move this into set_muting() but don't call set_muting() from places a user wouldn't
                    await self.set_muting(not self.muting)
                    await self.control_panel.update()
                    self.last_mute_time = timeit.default_timer()
            elif emoji.name == '©':
                if self.mimic is None:
                    await self.set_mimic(member)
                    await self.control_panel.update()
                elif member == self.mimic:
                    await self.set_mimic(None)
                    await self.control_panel.update()
            elif emoji.name == '🔄':
                for tracked_member in self.tracked_members:
                    if tracked_member.state == "dead":
                        tracked_member.state = "alive"
                await self.set_muting(False)
                await self.control_panel.update()
            # TODO: fetch_message() exception handling (idk if it matters in here tho)
            message = await self.text_channel.fetch_message(message_id)
            await message.remove_reaction(emoji, member)
