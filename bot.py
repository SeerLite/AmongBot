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

GUILD_ID = 691468513239367761
VOICE_CHANNEL = "Among Us"
TEXT_CHANNEL = "amongbot"
EXCLUDE_ROLE = "Music Botss"

client = discord.Client()

client.managed_guild = None
client.among_us_vc = None
client.litebot_channel = None
client.excluded_role = None

client.mimic = None
client.is_muting = False
client.tracked_members = []
client.control_panel = None

class TrackedMember():
    def __init__(self, member, is_listed=True, is_dead=False):
        self.member = member
        self.is_listed = is_listed
        self.is_dead = is_dead

@client.event
async def on_ready():
    print("Bot is online.")
    client.managed_guild = discord.utils.get(client.guilds, id=GUILD_ID)
    client.litebot_channel = discord.utils.get(client.managed_guild.text_channels, name=TEXT_CHANNEL)
    client.among_us_vc = discord.utils.get(client.managed_guild.voice_channels, name=VOICE_CHANNEL)
    client.excluded_role = discord.utils.get(client.managed_guild.roles, name=EXCLUDE_ROLE)
    client.tracked_members = client.among_us_vc.members
    client.tracked_members = list(filter(lambda m: not client.excluded_role in m.roles, client.tracked_members))
    client.tracked_members = [TrackedMember(member) for member in client.tracked_members] # convert to dicts
    await send_control_panel()

@client.event
async def on_message(message):
    if message.author == client.user or message.channel != client.litebot_channel:
        return
    if message.content.isdigit():
        index = int(message.content) - 1
        if index in range(len(client.tracked_members)):
            await message.delete()
            client.tracked_members[index].is_dead = not client.tracked_members[index].is_dead
            await set_mute(client.is_muting)
            await update_control_panel()

async def send_control_panel():
    if client.control_panel:
        await client.control_panel.delete()
    client.control_panel = await client.litebot_channel.send("```\n```")
    await client.control_panel.add_reaction('🔈')
    await client.control_panel.add_reaction('©')
    await client.control_panel.add_reaction('🔄')
    await update_control_panel()

async def update_control_panel():
    if client.control_panel:
        member_list = "\n".join((str(client.tracked_members.index(tracked_member) + 1) + ": " + tracked_member.member.display_name + (" (DEAD)" if tracked_member.is_dead else "") for tracked_member in filter(lambda m: m.is_listed, client.tracked_members)))
        if client.mimic:
            mimic_text = f"Mimicking: {client.mimic.display_name}"
        else:
            mimic_text = "Not mimicking anyone! React with :copyright: to mimic you!"
        await client.control_panel.edit(content=f"**Muting:** {'Yes' if client.is_muting else 'No'}\nMembers in Among Us:\n```{member_list}\n```{mimic_text}")

async def set_mute(mute_state):
    client.is_muting = mute_state
    tasks = []
    for tracked_member in client.tracked_members:
        if tracked_member.is_listed:
            if tracked_member.is_dead:
                if not tracked_member.member.voice.mute:
                    tasks.append(tracked_member.member.edit(mute=True))
            elif tracked_member.member.voice.mute != mute_state:
                if tracked_member.member == client.mimic:
                    tasks.append(tracked_member.member.edit(mute=mute_state))
                else:
                    tasks.append(tracked_member.member.edit(mute=mute_state))
    await asyncio.gather(*tasks)

async def set_mimic(member):
    if member:
        if member.voice and member.voice.channel == client.among_us_vc:
            client.mimic = member
            await set_mute(client.is_muting)
            await update_control_panel()
            return True
        else:
            return False
    else:
        client.mimic = None
        await update_control_panel()

@client.event
async def on_voice_state_update(member, before, after):
    if client.excluded_role in member.roles:
        return
    if member == client.mimic:
        if after.channel == client.among_us_vc: # Status changed inside channel
            if before.self_deaf != after.self_deaf:
                await set_mute(after.self_deaf)
                await update_control_panel()
        else:                                # Whoops, not in channel anymore?
            await set_mimic(None)
    if before.channel != after.channel:
        if after.channel == client.among_us_vc:
            if not member in (tracked_member.member for tracked_member in client.tracked_members):
                client.tracked_members.append(TrackedMember(member))
                await update_control_panel()
            else:
                for tracked_member in client.tracked_members:
                    if member == tracked_member.member and not tracked_member.is_listed:
                        tracked_member.is_listed = True
                        await update_control_panel()
        elif after.channel != client.among_us_vc:
            if len(client.among_us_vc.members) == 0:                                             # clear all tracked_members
                # TODO: make this all a new flag for set_mute (e.g only_managed=False) {
                client.is_muting = False
                tasks = []
                for tracked_member in client.tracked_members:
                    if tracked_member.member.voice:
                        tasks.append(tracked_member.member.edit(mute=False))
                await asyncio.gather(*tasks)
                # }
                client.tracked_members = []
                await update_control_panel()
            elif member in (tracked_member.member for tracked_member in client.tracked_members): # stop listing tracked_members who leave (but don't stop tracking them!)
                # TODO: don't stop tracking muted members
                for tracked_member in client.tracked_members:
                    if member == tracked_member.member and tracked_member.is_listed:
                        tracked_member.is_listed = False
                        await update_control_panel()

@client.event
async def on_reaction_add(reaction, member):
    if member == client.user:
        return
    if reaction.message.id == client.control_panel.id:
        if reaction.emoji == '🔈':
            await set_mute(not client.is_muting)
            await update_control_panel()
        elif reaction.emoji == '©':
            if client.mimic is None:
                await set_mimic(member)
            elif member == client.mimic:
                await set_mimic(None)
        elif reaction.emoji == '🔄':
            for tracked_member in client.tracked_members:
                tracked_member.is_dead = False
            await set_mute(False)
            await update_control_panel()
    await reaction.remove(member)

client.run(TOKEN)

