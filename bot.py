import os, sys, asyncio
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

class AlreadyDefinedError(Error):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg

class TrackedMember():
    def __init__(self, member, *, list=True, dead=False, mute=False, ignore=False):
        self.member = member
        self.list = list
        self.dead = dead
        self.mute = mute
        self.ignore = ignore

class BotPresence():
    @classmethod
    async def create(cls, guild, *, text_channel=None, voice_channel=None, excluded_roles=[], muting=False, mimic=None, control_panel=None):
        self = BotPresence()

        self.guild = guild
        self.text_channel = text_channel
        self.voice_channel = voice_channel
        self.excluded_roles = excluded_roles
        self.muting = muting
        self.mimic = mimic
        self.control_panel = control_panel
        self.tracked_members = []

        if self.text_channel and self.voice_channel:
            await self.track_current_voice()
            #await self.send_control_panel() # or just get the old control_panel back?

        return self

    async def set_text_channel(self, channel):
        #TODO: check for permissions in channel here
        if channel == self.text_channel:
            raise AlreadyDefinedError("Already listening to channel for commands")
        self.text_channel = channel
        return self.text_channel

    async def set_voice_channel(self, member):
        if member.voice:
            if member.voice.channel == self.voice_channel:
                raise AlreadyDefinedError("Already tracking voice channel")
                return
            #TODO: check for permissions in vc here
            self.voice_channel = member.voice.channel
            await self.track_current_voice()
            return self.voice_channel
        else:
            if self.voice_channel is None:
                raise AlreadyDefinedError("Not tracking any voice channel")
            self.voice_channel = None
    # TODO: we're creating tracked_members = [] above but below we discard it and just take voice_channel.members. do something about this
    async def track_current_voice(self):
        await self.set_mute(False, only_listed=False)
        self.tracked_members = [TrackedMember(member) for member in self.voice_channel.members if not any((role in member.roles for role in self.excluded_roles))]

    # TODO: maybe it's a good idea to use ext.commands instead of manually doing the stuff
    async def on_message(self, message):
        if message.guild != self.guild:
            return
        if message.content == "among:setup":
            try:
                await self.set_text_channel(message.channel)
            except AlreadyDefinedError:
                pass

            try:
                await self.set_voice_channel(message.author)
                await self.text_channel.send(f"All good! Listening for commands only on {self.text_channel.mention} and tracking {self.voice_channel.name}.")
                await self.send_control_panel()
            except AlreadyDefinedError:
                if self.voice_channel:
                    await self.text_channel.send(f"Already set up! This is {client.user.display_name}'s channel and currently tracking {self.voice_channel.name}.")
                else:
                    await self.text_channel.send(f"Error! User {message.author.mention} not in any voice channel on this server! Please join a voice channel first!")
                    self.text_channel = None # TODO: maybe call set_channel(None) instead?
        if message.content == "among:text":
            try:
                await self.set_text_channel(message.channel)
                await self.text_channel.send(f"Current channel {self.text_channel.mention} set as {client.user.name}'s channel!\n"
                                             f"Now accepting commands here.")
                if self.voice_channel:
                    await self.send_control_panel()
            except AlreadyDefinedError:
                await self.text_channel.send(f"Error! This channel is already {client.user.name}'s channel.")
        elif message.channel == self.text_channel:
            if message.content == "among:vc":
                try:
                    if await self.set_voice_channel(message.author):
                        await self.text_channel.send(f"{self.voice_channel.name} set as tracked voice channel!")
                        await self.send_control_panel()
                    elif self.control_panel:
                        await self.control_panel.delete()
                        self.control_panel = None
                        await self.text_channel.send(f"User {message.author.mention} not in any voice channel on this server. Stopped tracking voice channel.")
                except AlreadyDefinedError:
                    if self.voice_channel:
                        await self.text_channel.send(f"Error! {self.voice_channel.name} is already tracked. To untrack, run `among:vc` while not connected to any channel.")
                    else:
                        await self.text_channel.send(f"Error! User {message.author.mention} not in any voice channel on this server! Please join a voice channel first!")
            elif message.content.startswith("among:excluderole"):
                if message.role_mentions:
                    self.excluded_roles.extend(message.role_mentions)
                    # unmute all members from newly excluded role:
                    tasks = []
                    for member in (tracked_member.member for tracked_member in self.tracked_members if any((role in tracked_member.member.roles for role in self.excluded_roles))):
                        tasks.append(member.edit(mute=False))
                    asyncio.gather(*tasks)

                    self.tracked_members = [tracked_member for tracked_member in self.tracked_members if not any((role in tracked_member.member.roles for role in self.excluded_roles))]
                    await self.text_channel.send(f"Now excluding roles:\n{' '.join((role.mention for role in self.excluded_roles))}")
                    await self.update_control_panel()
                else:
                    await self.text_channel.send("Error! No role mentions detected!\nUsage: `among:excluderole <role mention>...`")
            elif message.content.isdigit() or (message.content[0] == "-" and message.content[1:].isdigit()):
                index = abs(int(message.content)) - 1
                if index in range(len(self.tracked_members)):
                    await message.delete()
                    if int(message.content) > 0:
                        if not self.tracked_members[index].ignore:
                            self.tracked_members[index].dead = not self.tracked_members[index].dead
                    else: # if index is negative, toggle ignore instead of dead
                        self.tracked_members[index].ignore = not self.tracked_members[index].ignore
                    await self.set_mute(self.muting)
                    await self.update_control_panel()

    async def send_control_panel(self):
        if self.control_panel:
            await self.control_panel.delete()
        self.control_panel = await self.text_channel.send("```\n```")
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
        for tracked_member in (tracked_member for tracked_member in self.tracked_members if tracked_member.list):
            control_panel_text += f"{self.tracked_members.index(tracked_member) + 1}. {'(IGNORED)' if tracked_member.ignore else ' (DEAD)  ' if tracked_member.dead else ' (MUTED) ' if tracked_member.mute else ' (ALIVE) '} {tracked_member.member.display_name.ljust(max((len(tracked_member.member.display_name) for tracked_member in self.tracked_members)))} | {tracked_member.member.name}#{tracked_member.member.discriminator}\n"
        control_panel_text += "```"
        if self.mimic:
            control_panel_text += f"**Mimicking:** {self.mimic.mention}"
        else:
            control_panel_text += "Not mimicking! React with :copyright: to mimic you!"
        await self.control_panel.edit(content=control_panel_text)

    async def set_mute(self, mute_state, *, only_listed=True):
        self.muting = mute_state
        tasks = []
        for tracked_member in self.tracked_members:
            if not tracked_member.ignore and (tracked_member.list or not only_listed) and tracked_member.member.voice and tracked_member.member.voice.channel == self.voice_channel:
                if tracked_member.dead:
                    if not tracked_member.member.voice.mute:
                        tasks.append(tracked_member.member.edit(mute=True))
                        tracked_member.mute = True
                elif tracked_member.member.voice.mute != mute_state:
                    tasks.append(tracked_member.member.edit(mute=mute_state))
                    tracked_member.mute = mute_state
        await asyncio.gather(*tasks)

    async def set_mimic(self, member):
        if member:
            if member.voice and member.voice.channel == self.voice_channel:
                self.mimic = member
                await self.set_mute(self.muting) # TODO: maybe set_mute() with no args should default to current mute
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
        if any((role in member.roles for role in self.excluded_roles)):
            return
        if member == self.mimic:
            if after.channel == self.voice_channel: # Status changed inside channel
                if before.self_deaf != after.self_deaf:
                    await self.set_mute(after.self_deaf)
                    await self.update_control_panel()
            else:                                # Whoops, not in channel anymore?
                await self.set_mimic(None)
                await self.update_control_panel()
        if before.channel != after.channel:
            if after.channel == self.voice_channel:
                if not member in (tracked_member.member for tracked_member in self.tracked_members):
                    self.tracked_members.append(TrackedMember(member, ignore=True if member.voice.mute != self.muting else False)) # ignore new members that don't match current mute state
                    await self.update_control_panel()
                else:
                    for tracked_member in self.tracked_members:
                        if member == tracked_member.member and not tracked_member.list:
                            tracked_member.list = True
                            await self.update_control_panel()
            elif after.channel != self.voice_channel:
                if member in (tracked_member.member for tracked_member in self.tracked_members): # stop listing tracked_members who leave (but don't stop tracking them unless there's no more tracked members!)
                    for tracked_member in self.tracked_members:
                        if member == tracked_member.member and tracked_member.list and (not tracked_member.mute or tracked_member.ignore):
                            tracked_member.list = False

                if not any((tracked_member.list for tracked_member in self.tracked_members)): # reset indexes when managed members leave
                    await self.set_mute(False, only_listed=False)
                    self.tracked_members = []
                await self.update_control_panel()

    async def on_reaction_add(self, reaction, member):
        if member.guild != self.guild:
            return
        if self.control_panel is None:
            return
        if reaction.message.id == self.control_panel.id: # TODO: why doesn't this work here without .id?
            if reaction.emoji == '🔈':
                await self.set_mute(not self.muting)
                await self.update_control_panel()
            elif reaction.emoji == '©':
                if self.mimic is None:
                    await self.set_mimic(member)
                    await self.update_control_panel()
                elif member == self.mimic:
                    await self.set_mimic(None)
                    await self.update_control_panel()
            elif reaction.emoji == '🔄':
                for tracked_member in self.tracked_members:
                    tracked_member.dead = False
                await self.set_mute(False)
                await self.update_control_panel()
            await reaction.remove(member)

@client.event
async def on_ready():
    print("Bot is online.")
    client.presences = []
    for guild in client.guilds:
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
        await presence.on_message(message) # NOTE: will receive messages from all guilds

@client.event
async def on_voice_state_update(member, before, after):
    if member == client.user:
        return
    for presence in client.presences:
        await presence.on_voice_state_update(member, before, after) # NOTE: will receive updates from all guilds

@client.event
async def on_reaction_add(reaction, member):
    if member == client.user:
        return
    for presence in client.presences:
        await presence.on_reaction_add(reaction, member) # NOTE: will receive reactions from all guilds

if __name__ == '__main__':
    client.run(TOKEN)

