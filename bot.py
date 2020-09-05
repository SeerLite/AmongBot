import os, sys, asyncio
import discord
from discord.ext import commands

if not (TOKEN := os.getenv("DISCORD_TOKEN")):
    try:
        with open(".token") as token_file:
            TOKEN = token_file.read()
    except FileNotFoundError:
        print("No .token file found! Please create it or pass it through DISCORD_TOKEN environment variable.")
        sys.exit(1)

GUILD_ID = 691468513239367761
VOICE_CHANNEL = "Among Us"
TEXT_CHANNEL = "litebot"
EXCLUDE_ROLE = "Music Botss"

bot = commands.Bot(command_prefix="lt:")

bot.managed_guild = None
bot.among_us_vc = None
bot.litebot_channel = None

bot.mimic = None
bot.is_muting = False
bot.tracked_members = []
bot.control_panel = None

class Tracked_member():
    def __init__(self, member, is_visible=True, is_dead=False):
        self.member = member
        self.is_visible = is_visible
        self.is_dead = is_dead

@bot.event
async def on_ready():
    print("Bot is online.")
    bot.managed_guild = discord.utils.get(bot.guilds, id=GUILD_ID)
    bot.litebot_channel = discord.utils.get(bot.managed_guild.text_channels, name=TEXT_CHANNEL)
    bot.among_us_vc = discord.utils.get(bot.managed_guild.voice_channels, name=VOICE_CHANNEL)
    bot.tracked_members = bot.among_us_vc.members
    bot.tracked_members = list(filter(lambda m: not discord.utils.get(m.roles, name=EXCLUDE_ROLE), bot.tracked_members))
    bot.tracked_members = [Tracked_member(member) for member in bot.tracked_members] # convert to dicts
    await send_control_panel()

@bot.event
async def on_message(message):
    if message.author == bot.user or message.channel != bot.litebot_channel:
        return
    if message.content.isdigit():
        index = int(message.content) - 1
        if index in range(len(bot.tracked_members)):
            await message.delete()
            bot.tracked_members[index].is_dead = not bot.tracked_members[index].is_dead
            await set_mute(bot.is_muting)

async def send_control_panel():
    if bot.control_panel:
        await bot.control_panel.delete()
    bot.control_panel = await bot.litebot_channel.send("```\n```")
    await bot.control_panel.add_reaction('🔈')
    await bot.control_panel.add_reaction('©')
    await bot.control_panel.add_reaction('💩')
    await update_control_panel()

async def update_control_panel():
    if bot.control_panel:
        member_list = "\n".join([str(bot.tracked_members.index(tracked_member) + 1) + ": " + tracked_member.member.display_name + (" (DEAD)" if tracked_member.is_dead else "") for tracked_member in filter(lambda m: m.is_visible, bot.tracked_members)])
        if bot.mimic:
            mimic_text = f"Mimicking: {bot.mimic.display_name}"
        else:
            mimic_text = "Not mimicking anyone! React with :copyright: to mimic you!"
        await bot.control_panel.edit(content=f"**Muting:** {'Yes' if bot.is_muting else 'No'}\nMembers in Among Us:\n```{member_list}\n```{mimic_text}")

async def set_mute(mute_state):
    bot.is_muting = mute_state
    await update_control_panel()
    tasks = []
    for tracked_member in bot.tracked_members:
        if tracked_member.is_visible: # in vc
            if tracked_member.is_dead:
                tasks.append(tracked_member.member.edit(mute=True, deafen=False))
            elif tracked_member.member == bot.mimic:
                tasks.append(tracked_member.member.edit(mute=mute_state, deafen=False))
            else:
                tasks.append(tracked_member.member.edit(mute=mute_state, deafen=mute_state))
    await asyncio.gather(*tasks)

# Raw mimic function
async def set_mimic(member):
    if member:
        if member.voice and member.voice.channel == bot.among_us_vc:
            bot.mimic = member
            await set_mute(bot.is_muting)
            return True
        else:
            return False
    else:
        # TODO: different behavior depending on if user left or just stopped mimicking.
        bot.mimic = None
        await update_control_panel()

@bot.event
async def on_voice_state_update(member, before, after):
    if discord.utils.get(member.roles, name=EXCLUDE_ROLE):
        return
    if member == bot.mimic:
        if after.channel == bot.among_us_vc: # Status changed inside channel
            if before.self_deaf != after.self_deaf:
                await set_mute(after.self_deaf)
        else:                                # Whoops, not in channel anymore?
            await set_mimic(None)
    # TODO: optimize this. it's called n times each time set_mute is done. n is the amount of members in vc
    if after.channel == bot.among_us_vc:
        if not member in [tracked_member.member for tracked_member in bot.tracked_members]:
            bot.tracked_members.append(Tracked_member(member))
            await update_control_panel()
        else:
            for tracked_member in bot.tracked_members:
                if member == tracked_member.member and not tracked_member.is_visible:
                    tracked_member.is_visible = True
                    await update_control_panel()
    elif after.channel != bot.among_us_vc and member in [tracked_member.member for tracked_member in bot.tracked_members]:
        for tracked_member in bot.tracked_members:
            if member == tracked_member.member and tracked_member.is_visible:
                tracked_member.is_visible = False
                await update_control_panel()

@bot.event
async def on_reaction_add(reaction, member):
    if member == bot.user:
        return
    if reaction.message.id == bot.control_panel.id:
        if reaction.emoji == '🔈':
            if bot.is_muting:
                await set_mute(False)
            else:
                await set_mute(True)
        elif reaction.emoji == '©':
            if bot.mimic is None:
                await set_mimic(member)
            elif member == bot.mimic:
                await set_mimic(None)
        elif reaction.emoji == '💩':
            for tracked_member in bot.tracked_members:
                tracked_member.is_dead = False
            await set_mute(False)
    await reaction.remove(member)

bot.run(TOKEN)

