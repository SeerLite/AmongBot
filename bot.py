import os, sys, asyncio
import discord
import time

if not (TOKEN := os.getenv("DISCORD_TOKEN")):
    try:
        with open(".token") as token_file:
            TOKEN = token_file.read()
    except FileNotFoundError:
        print("No .token file found! Please create it or pass it through DISCORD_TOKEN environment variable.")
        sys.exit(1)

VOICE_CHANNEL = "Among Us"
TEXT_CHANNEL = "amongbot"
EXCLUDE_ROLE = "Music Botss"

client = discord.Client()

class TrackedMember():
    # TODO: make these kw only args
    def __init__(self, member, is_listed=True, is_dead=False, mute=False):
        self.member = member
        self.is_listed = is_listed
        self.is_dead = is_dead
        self.mute = mute

class BotPresence():
    @classmethod
    async def create(cls, guild, *, text_channel=None, voice_channel=None, excluded_roles=None, is_muting=False, mimic=None, tracked_members=None):
        self = BotPresence()

        self.guild = guild
        self.text_channel = text_channel
        self.voice_channel = voice_channel
        self.excluded_roles = excluded_roles or []
        self.is_muting = is_muting
        self.mimic = mimic
        self.tracked_members = tracked_members
        self.control_panel = None

        if self.text_channel and self.voice_channel:
            if self.tracked_members is None:
                self.track_current_voice()
            await self.send_control_panel()

        return self

    def track_current_voice(self):
        await self.set_mute(False, only_listed=False)
        self.tracked_members = []
        self.tracked_members = list(filter(lambda m: not any((role in m.roles for role in self.excluded_roles)), self.voice_channel.members))
        self.tracked_members = [TrackedMember(member) for member in self.tracked_members]

    async def on_message(self, message):
        if message.guild != self.guild:
            return
        if message.content == "among:setup":
            #TODO: this does set_text() and set_vc() in one command
            pass
        if message.content == "among:text": #TODO: make this a method
            #TODO: check for permissions in channel here
            self.text_channel = message.channel
            await self.text_channel.send(f"Current channel {self.text_channel.name} set as {client.user.name}'s channel!")
            if self.voice_channel:
                await self.send_control_panel()
            else:
                await self.text_channel.send("Please define a voice channel by joining it and using among:vc")
        elif message.channel == self.text_channel:
            #TODO: check for permissions in vc here
            if message.content == "among:vc": #TODO: make  this method
                if message.author.voice:
                    self.voice_channel = message.author.voice.channel
                    self.track_current_voice()
                    await self.text_channel.send(f"{self.voice_channel.name} set as tracked voice channel!")
                    await self.send_control_panel()
                elif self.control_panel:
                    await self.text_channel.send(f"User {message.author} not in any voice channel on this server. Stopped tracking {self.voice_channel}.")
                    await self.control_panel.delete()
                    self.control_panel = None
                else:
                    await self.text_channel.send(f"Error! User {message.author} not in any voice channel on this server! Please join a voice channel first!")
            elif message.content.isdigit():
                index = int(message.content) - 1
                if index in range(len(self.tracked_members)):
                    await message.delete()
                    self.tracked_members[index].is_dead = not self.tracked_members[index].is_dead
                    await self.set_mute(self.is_muting)
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
        member_list = "\n".join((str(self.tracked_members.index(tracked_member) + 1) + ": " + tracked_member.member.display_name + (" (DEAD)" if tracked_member.is_dead else "") for tracked_member in filter(lambda m: m.is_listed, self.tracked_members)))
        if self.mimic:
            mimic_text = f"Mimicking: {self.mimic.display_name}"
        else:
            mimic_text = "Not mimicking anyone! React with :copyright: to mimic you!"
        await self.control_panel.edit(content=f"**Muting:** {'Yes' if self.is_muting else 'No'}\nMembers in {self.voice_channel.name}:\n```{member_list}\n```{mimic_text}")

    async def set_mute(self, mute_state, *, only_listed=True):
        self.is_muting = mute_state
        tasks = []
        for tracked_member in self.tracked_members:
            if (tracked_member.is_listed or not only_listed) and tracked_member.member.voice and tracked_member.member.voice.channel == self.voice_channel:
                if tracked_member.is_dead:
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
                await self.set_mute(self.is_muting)
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
                    self.tracked_members.append(TrackedMember(member))
                    await self.update_control_panel()
                else:
                    for tracked_member in self.tracked_members:
                        if member == tracked_member.member and not tracked_member.is_listed:
                            tracked_member.is_listed = True
                            await self.update_control_panel()
            elif after.channel != self.voice_channel:
                if member in (tracked_member.member for tracked_member in self.tracked_members): # stop listing tracked_members who leave (but don't stop tracking them unless there's no more tracked members!)
                    for tracked_member in self.tracked_members:
                        if member == tracked_member.member and tracked_member.is_listed and not tracked_member.mute:
                            tracked_member.is_listed = False

                if not any((tracked_member.is_listed for tracked_member in self.tracked_members)): # reset indexes when managed members leave
                    await self.set_mute(False, only_listed=False)
                    self.tracked_members = []
                await self.update_control_panel()

    async def on_reaction_add(self, reaction, member):
        if member.guild != self.guild:
            return
        if reaction.message.id == self.control_panel.id: # TODO: why doesn't this work here without .id?
            if reaction.emoji == '🔈':
                await self.set_mute(not self.is_muting)
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
                    tracked_member.is_dead = False
                await self.set_mute(False)
                await self.update_control_panel()
            else:
                print("nope")
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
    for i, presence in enumerate(client.presences):
        if guild == presence.guild:
            del client.presences[i]
            break

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

client.run(TOKEN)

