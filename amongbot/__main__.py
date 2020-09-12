import os
import sys
import json

from .client import Client

# load token from env, fall back to .token file
if not (TOKEN := os.getenv("DISCORD_TOKEN")):
    try:
        with open(".token") as token_file:
            TOKEN = token_file.read()
    except FileNotFoundError:
        print("No .token file found! Please create it or pass it through DISCORD_TOKEN environment variable.")
        sys.exit(1)

client = Client()

try:
    with open("data.json") as save_file:
        client.save_data = json.load(save_file)
except FileNotFoundError:
    client.save_data = {}
client.run(TOKEN)
