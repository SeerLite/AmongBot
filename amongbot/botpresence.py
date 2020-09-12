import asyncio
import json
from .trackedmember import TrackedMember

from .errors import SameValueError


class BotPresence:
    @classmethod
    async def create(cls, guild, client, *, text_channel_id=None, voice_channel_id=None, control_panel_id=None, excluded_roles_ids=[]):
        self = BotPresence()

        self.guild = guild
        self.client = client
        self._text_channel = None
        self._voice_channel = None
        self.control_panel = None

        if text_channel_id:
            self._text_channel = self.guild.get_channel(int(text_channel_id))
        if voice_channel_id:
            self._voice_channel = self.guild.get_channel(int(voice_channel_id))
        if control_panel_id:
            # TODO: fetch_message() can raise exceptions, handle them
            self.control_panel = await self.text_channel.fetch_message(int(control_panel_id))
        self._excluded_roles = frozenset(self.guild.get_role(int(id)) for id in excluded_roles_ids)  # frozen cause we're only assigning anyway
        self._muting = False
        self.muting_lock = asyncio.Lock()
        self.mimic_undeafen_event = asyncio.Event()
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
            raise SameValueError(channel)
        self._text_channel = channel
        self.save()

    @property
    def voice_channel(self):
        return self._voice_channel

    @voice_channel.setter
    def voice_channel(self, channel):
        if self._voice_channel == channel:
            raise SameValueError(channel)
        # TODO: check for permissions in vc here
        self._voice_channel = channel
        self.save()

    @property
    def excluded_roles(self):
        return self._excluded_roles

    async def set_excluded_roles(self, excluded_roles):
        if self._excluded_roles == excluded_roles:
            raise SameValueError(excluded_roles)
        if new_excludes := excluded_roles.difference(self._excluded_roles):  # only if there's _new_ roles
            # unmute and untrack all members from newly excluded role
            await asyncio.gather(*(tracked_member.set_mute(False) for tracked_member in self.tracked_members if any((role in new_excludes for role in tracked_member.member.roles))))  # TODO: maybe make a function/method for the generator here?
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

    async def set_muting(self, mute_state):
        async with self.muting_lock:
            self._muting = mute_state
            await asyncio.gather(*(tracked_member.set_mute(mute_state) for tracked_member in self.tracked_members))

    def save(self):
        if not str(self.guild.id) in self.client.save_data:
            self.client.save_data[str(self.guild.id)] = {}
        for name, value in (("text", self.text_channel), ("voice", self.voice_channel), ("control", self.control_panel)):
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

    # TODO: maybe it's a good idea to use ext.commands instead of manually doing the stuff
    async def on_message(self, message):
        if message.guild != self.guild:
            return
        if message.content == "among:setup":  # TODO: make this a method?
            # TODO: DRY this
            if message.author.voice:
                try:
                    self.text_channel = message.channel
                    self.voice_channel = message.author.voice.channel
                    await self.track_current_voice()
                    await self.text_channel.send(f"All good! Listening for commands only on {self.text_channel.mention} and tracking {self.voice_channel.name}.")
                    await self.send_control_panel()
                except SameValueError as error:
                    if error.args[0] == message.channel:
                        try:
                            self.voice_channel = message.author.voice.channel
                            await self.track_current_voice()
                            await self.text_channel.send(f"All good! Listening for commands only on {self.text_channel.mention} and tracking {self.voice_channel.name}.")
                            await self.send_control_panel()
                        except SameValueError as error:
                            if error.args[0] == message.author.voice.channel:
                                await self.text_channel.send(f"Already set up! This is {self.client.user.display_name}'s channel and currently tracking {self.voice_channel.name}.")
                    elif error.args[0] == message.author.voice.channel:
                        await self.text_channel.send(f"All good! Listening for commands only on {self.text_channel.mention} and tracking {self.voice_channel.name}.")
                        await self.send_control_panel()
            else:
                await message.channel.send(f"Error! User {message.author.mention} not in any voice channel on this server! Please join a voice channel first!")
        elif message.content == "among:text":
            try:
                self.text_channel = message.channel
                await self.text_channel.send(f"Current channel {self.text_channel.mention} set as {self.client.user.name}'s channel!\n"
                                             f"Now accepting commands here.")
                if self.voice_channel:
                    await self.send_control_panel()
            except SameValueError:
                await self.text_channel.send(f"Error! This channel is already {self.client.user.name}'s channel.")
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
            elif all(received_index.isdigit() or (received_index and message.content[0] == "-" and received_index[1:].isdigit()) for received_index in message.content.split(" ")):
                await message.delete()
                for received_index in message.content.split(" "):
                    index = abs(int(received_index)) - 1
                    if index in range(len(self.tracked_members)):
                        if int(received_index) > 0:
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
            f"**Muting:** `{'Yes' if self.muting else 'No'}`\n"
            f"**Tracked users:**\n"
        )
        for tracked_member in self.tracked_members:
            control_panel_text += (f"`{' --' if not tracked_member.is_in_vc else str(self.tracked_members.index(tracked_member) + 1).rjust(3)}. "
                                   f"{tracked_member.member.display_name.ljust(max(len(tracked_member.member.display_name) for tracked_member in self.tracked_members))} "
                                   f"{ ('(' + tracked_member.state + ')').rjust(9)}` "
                                   f"{tracked_member.member.mention}\n")
        if self.mimic:
            control_panel_text += f"**Mimicking:** {self.mimic.mention}. Quickly deafen and undeafen yourself to toggle global mute."
        else:
            control_panel_text += "Not mimicking! React with :copyright: to mimic you!"
        await self.control_panel.edit(content=control_panel_text)

    async def set_mimic(self, member):  # TODO: use TrackedMember instead of Member
        if member:
            if member.voice and member.voice.channel == self.voice_channel:  # TODO: and make this use is_in_vc
                self.mimic = member
                await self.set_muting(self.muting)  # TODO: maybe set_muting() with no args should default to current mute (or maybe set_muting shouldn't do all it does? (or maybe it should be renamed??))
                return True
            else:
                return False
        else:
            self.mimic = None

    async def on_voice_state_update(self, member, before, after):
        if member.guild != self.guild or self.voice_channel is None or any((role in self.excluded_roles for role in member.roles)):
            return
        if member == self.mimic:
            if after.channel == self.voice_channel:  # Status changed inside channel
                if not before.self_deaf and after.self_deaf:    # Deafened
                    try:
                        await asyncio.wait_for(self.mimic_undeafen_event.wait(), 1)
                        await self.set_muting(not self.muting)
                        await self.update_control_panel()
                    except asyncio.TimeoutError:
                        pass
                elif before.self_deaf and not after.self_deaf:  # Undeafened
                    self.mimic_undeafen_event.set()
                    self.mimic_undeafen_event.clear()
            else:                                    # Whoops, not in channel anymore?
                await self.set_mimic(None)
                await self.update_control_panel()
        if before.channel != after.channel:
            if after.channel == self.voice_channel:
                if member not in (tracked_member.member for tracked_member in self.tracked_members):
                    self.tracked_members.append(TrackedMember(member, self, ignore=True if member.voice.mute != self.muting else False))  # ignore new members that don't match current mute state
                await self.update_control_panel()
            elif after.channel != self.voice_channel:
                if not any((tracked_member.is_in_vc for tracked_member in self.tracked_members)):  # reset indexes when all managed members leave
                    await self.set_muting(False)
                    self.tracked_members = []
                await self.update_control_panel()

    async def on_reaction_add(self, emoji, message_id, member):
        if member.guild != self.guild or self.control_panel is None:
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
            # TODO: fetch_message() exception handling (idk if it matters in here tho)
            message = await self.text_channel.fetch_message(message_id)
            await message.remove_reaction(emoji, member)
