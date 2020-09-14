# [AmongBot](https://gitlab.com/SeerLite/AmongBot) (WIP)
Yet another Discord bot for muting members of a voice channel when playing Among Us.

## Features
* Track a specific voice channel on your server.
* Intuitive control panel to easily mute and unmute all members in the tracked channel.
* Set members as "dead" so they don't get unmuted by a global toggle.
* Mimic: Quickly deafen and un-deafen yourself to toggle global mute.
* Ignore members that either aren't playing, or should stay server-muted.
* Permanently exclude specific roles from being muted. Useful if you want to have a music bot running while playing!

## Usage
Please keep in mind this bot is still work in progress. If you need a bot that's easier to use or need a feature this one lacks, see [Similar Bots](#similar-bots).
1. Create a Discord application and bot.
2. Put the bot token in a file called token.txt.
3. Run the bot from the command line:
    Linux/Unix:
    ```
    python3 -m amongbot
    ```
    Windows:
    ```
    py -m amongbot
    ```
For information on how to use the bot inside the server, type `among:help`.

## Planned features
* Support for multiple voice channel tracking, for public Discord servers.
* Play an audio cue in the voice channel when muting/unmuting.
* OCR-scanning mode: Scan the screen contents and automatically mute/unmute members. For projects already implementing this, see [Similar Bots](#similar-bots).
* For more specific stuff, see todo.txt.

## Similar bots
Here's some other bots that implement similar features. Check them all out and use the one that works the best for you!
* Implementing OCR scanning of screen, for automatic muting:
  - https://github.com/denverquane/amongusdiscord
  - https://github.com/alpharaoh/AmongUsBot

## License
This bot is Free Software licensed under AGPL 3 or later.

