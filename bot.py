import os
import discord
from discord.ext import commands
import asyncio

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = 691468513239367761
VOICE_CHANNEL = "Among Us"
TEXT_CHANNEL = "litebot"

bot = commands.Bot(command_prefix="lt:")

bot.managed_guild = None
bot.among_us_vc = None
bot.litebot_channel = None

bot.mimic = None
bot.tracked_members = []
bot.managed_mutes = []
bot.control_panel = None

@bot.event
async def on_ready():
    print("Bot is online.")
    bot.managed_guild = discord.utils.get(bot.guilds, id=GUILD_ID)
    bot.litebot_channel = discord.utils.get(bot.managed_guild.text_channels, name=TEXT_CHANNEL)
    bot.among_us_vc = discord.utils.get(bot.managed_guild.voice_channels, name=VOICE_CHANNEL)
    bot.tracked_members = bot.among_us_vc.members
    bot.tracked_members = list(filter(lambda m: not discord.utils.get(m.roles, name="Music Bots"), bot.tracked_members))
    bot.tracked_members = [dict(member=member, is_visible=True) for member in bot.tracked_members] # convert to dicts
    await send_control_panel()

async def send_control_panel():
    if bot.control_panel:
        await bot.control_panel.delete()
    bot.control_panel = await bot.litebot_channel.send("```\n```")
    await bot.control_panel.add_reaction('🔈')
    await bot.control_panel.add_reaction('©')
    await update_control_panel()

async def update_control_panel():
    if bot.control_panel:
        member_list = "\n".join([str(bot.tracked_members.index(member_dict) + 1) + ": " + member_dict["member"].display_name for member_dict in filter(lambda m: m["is_visible"], bot.tracked_members)])
        if bot.mimic:
            mimic_text = f"Mimicking: {bot.mimic.display_name}"
        else:
            mimic_text = "Not mimicking anyone! React to :copyright: to mimic you!"
        await bot.control_panel.edit(content=f"Members in Among Us:\n```{member_list}\n```{mimic_text}")

async def set_mute(mute_state, check_managed=True):
    members = bot.among_us_vc.members
    if bot.mimic:
        members.remove(bot.mimic) # filter out mimicked member
    members = list(filter(lambda m: not discord.utils.get(m.roles, name="Music Bots"), members)) # filter out Music Bots
    members = list(filter(lambda m: m.voice.mute != mute_state, members)) # filter out users already server-muted/unmuted
    if mute_state:
        bot.managed_mutes += members
    if not mute_state and check_managed:
        members = list(filter(lambda m: m in bot.managed_mutes, members))
        bot.managed_mutes = []
    await asyncio.gather(*(member.edit(mute=mute_state) for member in members))
    return members

@bot.command(name="forceunmute", help=f"Force unmutes everyone in {VOICE_CHANNEL}")
async def forceunmute(ctx):
    muted_members = await set_mute(False, False)
    await ctx.send(f"Force unmuted everyone:\n{' - '.join((member.display_name for member in muted_members))}")

@bot.command(name="listmanaged", help="Lists managed mutes")
async def listmanaged(ctx):
    await ctx.send(f"Server muted members managed by LiteBot:\n{' - '.join((member.display_name for member in bot.managed_mutes))}")

# Raw mimic function
async def set_mimic(member):
    if member:
        if member.voice and member.voice.channel == bot.among_us_vc:
            bot.mimic = member
            await update_control_panel()
            return True
        else:
            return False
    else:
        bot.mimic = None
        await update_control_panel()

@bot.event
async def on_voice_state_update(member, before, after):
    if discord.utils.get(member.roles, name="Music Bots"):
        return
    if member == bot.mimic:
        if after.channel == bot.among_us_vc: # Status changed inside channel
            if before.self_mute != after.self_mute:
                if after.self_mute:
                    await set_mute(True)
                else:
                    await set_mute(False)
        else:                                # Whoops, not in channel anymore?
            await set_mimic(None)
    if after.channel == bot.among_us_vc:
        if not member in [member_dict["member"] for member_dict in bot.tracked_members]:
            bot.tracked_members.append(dict(member=member, is_visible=True))
        else:
            for member_dict in bot.tracked_members:
                if member == member_dict["member"]:
                    member_dict["is_visible"] = True
    elif after.channel != bot.among_us_vc and member in [member_dict["member"] for member_dict in bot.tracked_members]:
        for member_dict in bot.tracked_members:
            if member == member_dict["member"]:
                member_dict["is_visible"] = False
    await update_control_panel()

@bot.event
async def on_reaction_add(reaction, member):
    if member == bot.user:
        return
    await reaction.message.remove_reaction(reaction.emoji, member)
    if reaction.message.id == bot.control_panel.id:
        if reaction.emoji == '🔈':
            if len(bot.managed_mutes):
                await set_mute(False)
            else:
                await set_mute(True)
        elif reaction.emoji == '©':
            if bot.mimic is None:
                await set_mimic(member)
            elif member == bot.mimic:
                await set_mimic(None)

bot.run(TOKEN)

