import os
import sys
import json

from .client import Client

# load token from env, fall back to token.txt
if not (token := os.getenv("DISCORD_TOKEN")):
    try:
        with open("token.txt") as token_file:
            token = token_file.read()
    except FileNotFoundError:
        # TODO: auto-create token.txt?
        print("No token.txt file found! Please create it and paste your token, or pass it through the DISCORD_TOKEN environment variable.")
        sys.exit(1)


try:
    with open("data.json") as save_file:
        save_data = json.load(save_file)
        client = Client(save_data=save_data)
except FileNotFoundError:
    client = Client()
except json.JSONDecodeError:
    if os.stat("data.json").st_size == 0:
        client = Client()
    else:
        raise

client.run(token)
