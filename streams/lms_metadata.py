#!/usr/bin/python3
"""LMS Metadata Reader - a script for finding an LMS player with a given name and extracting the name of the song, album, and artist as well as getting the album picture"""

import os
import argparse
import re
import json
import time
from typing import Optional
import subprocess
import requests

class LMSMetadataReader:
  """A class for getting metadata from a Logitech Media Server."""

  # meta_ref is probably an unneccessary variable to pass as an arg since it's obscured from the user, but we can eventually make it an optional setting for the user
  def __init__(self, name: str, client: Optional[str], meta_ref: Optional[int] = 2, debug: Optional[bool] = False):
    self.player_name = name
    self.client = client
    self.server = None # {ip}:{port}
    self.meta_ref_rate = meta_ref
    self.debug = debug


  def flatten(self, lms_info: dict) -> dict:
    """ LMS returns data in a very verbose piecewise format to avoid name collisions,
          this makes it easier to use, by disregarding possible collisions"""
    x = 0
    flat_data = {}
    for item in lms_info:
      for info in item:
        flat_data[info] = lms_info[x][info]
      x += 1
    return flat_data

  def replace(self, data: dict) -> None:
    """Writes json data to a temp file, then replaces a read file with that data"""
    with open(f"lms_{str(self.player_name).replace(' ', '_')}_metadata_temp.json", 'wt', encoding='utf-8') as f:
      json.dump(data, f, indent = 2)
    os.replace(f"lms_{str(self.player_name).replace(' ', '_')}_metadata_temp.json", f"lms_{str(self.player_name).replace(' ', '_')}_metadata.json")

  def connect(self):
    """Discovers LMS Player and then requests metadata repetitively"""
    connected = False
    self.replace({'artist': 'Loading...', 'album': 'If loading takes a long time,', 'track': 'consider adding hostname to stream config', 'image_url': 'static/imgs/lms.png'})

    # When not connected, search for player to connect to by the proper name
    while not connected:
      try:
        # Much faster method of connecting to the metadata server using code from: https://github.com/ralph-irving/squeezelite/blob/master/tools/find_server.c
        if self.client is not None:
          ip = self.client
          port = "9000"
          self.server = f"{ip}:{port}"
        else:
          ip_find = subprocess.run(['bin/arm/find_lms_server'], check=True, capture_output=True, text=True)
          # Uses regex because ip_find spits out as '{Hostname}:{port} ({ip})', data is then formatted to output ip and port
          ip = re.search(r'\((.*?)\)', ip_find.stdout).group(1)
          port = re.search(r':(\d{4})', ip_find.stdout).group(1)
          self.server = f"{ip}:{port}"

        if self.debug:
          print(f"Found LMS Server: {ip}:{port}", flush=True)

        player_json = {"id": 1,	"method": "slim.request",	"params": [self.player_name, ["players", "-", 100, "playerid"]]}
        player_info = requests.get(f'http://{self.server}/jsonrpc.js', json=player_json, timeout=200)
        player_load = json.loads(player_info.text)
        players = player_load['result']['players_loop']

        for player in players:
          connected = player['connected']
          if connected and player['name'] == self.player_name:
            if self.debug:
              print(f'LMS Metadata connected to player: {self.player_name}')
            connected = True
          else:
            time.sleep(0.1)
      except Exception as e:
        # When first creating an LMS stream, there can be random errors that will close the while loop
        # typically when asking the player for info when there isn't a player linked to the stream yet
        if self.debug:
          print(f"Could not find server: {e}", flush=True)
        time.sleep(self.meta_ref_rate)

    while connected:
      try:
        track_json = {"id": 1, "method": "slim.request", "params": [ self.player_name, ["status", "-",100] ]}
        track_info = requests.post(f'http://{self.server}/jsonrpc.js 2>/dev/null', json=track_json, timeout=200)
        track_load = json.loads(track_info.text)

        track_id = track_load["result"]["playlist_loop"][0]["id"]
        song_json = {"id":2,"method":"slim.request","params":[ self.player_name, ["songinfo","-",100,f"track_id:{track_id}"]]}
        song_info = requests.post(f'http://{self.server}/jsonrpc.js 2>/dev/null', json=song_json, timeout=200)
        song_load = json.loads(song_info.text)

        song_data = self.flatten(song_load['result']['songinfo_loop'])
        track_data = self.flatten(track_load['result']['playlist_loop'])

        meta = {
          'artist': 'Loading...',
          'album': 'If loading takes a long time,',
          'track': 'consider adding hostname to stream config',
          'image_url': 'static/imgs/lms.png'
         }

        if self.debug:
          print(f"Current stream type: {song_data['type']}")

        if song_data['type'] == "MP3 Radio" or song_data['type'] == "AAC Radio" or song_data['type'] == "Radio" or song_data['type'] == "TEXT/X-JSON Radio":
          try:
            meta["track"] = track_data["title"]
            meta['artist'] = None
            meta['album'] = song_data['remote_title']
            meta["image_url"] = f"http://{self.server}/music/{song_data['coverid']}/cover.jpg?id={song_data['coverid']}"
          except KeyError:
            # Sometimes, KeyError will occur when switching between streams with different metadata formatting
            print(f"KeyError, trying again in {self.meta_ref_rate} seconds...")

            meta["track"] = song_data["title"]
            meta['image_url'] = 'static/imgs/lms.png'

        # Pandora and Spotify have a different formatting for their metadata than radio streams
        elif song_data['type'] == "MP3 (Pandora)" or song_data['type'] == "Ogg Vorbis (Spotify)":
          try:
            meta["track"] = song_data["title"]
            meta["artist"] = song_data["artist"]
            meta["album"] = song_data["album"]
            meta["image_url"] = song_data["artwork_url"]
          except KeyError:
            # Sometimes, KeyError will occur when switching between streams with different metadata formatting
            print(f"KeyError, trying again in {self.meta_ref_rate} seconds...")

            meta["track"] = song_data["title"]
            meta["image_url"] = song_data["artwork_url"]

        try:
          self.replace(meta)
        except:
          pass

        if self.debug:
          with open(f"{str(self.player_name).replace(' ', '_')}_track_raw.json", "w", encoding="UTF-8") as f:
            json.dump(track_load, f, indent = 2)
          with open(f"{str(self.player_name).replace(' ', '_')}_song_raw.json", "w", encoding="UTF-8") as f:
            json.dump(song_load, f, indent = 2)
      except Exception as e:
        print(f"Error: {e}, trying again in {self.meta_ref_rate} seconds...")

      time.sleep(self.meta_ref_rate)

if __name__ == '__main__':
  parser = argparse.ArgumentParser(description="LMS Metadata Reader - a script for finding an LMS player with a given name and extracting the name of the song, album, and artist as well as getting the album picture")
  parser.add_argument('--name', type=str, required=True, help='The name of the LMS Player')
  parser.add_argument('--client', type=str, help='The name of the client running the LMS server', metavar="SERVER_ADDRESS")
  parser.add_argument('--ref', type=int, default=2, help='The frequency of metadata refresh cycles')
  parser.add_argument('--debug', action='store_true', help='''d''ebug mode, activates various console logs so that you can debug in the command line,
                      also creates json dumps in the main directory: {player name}_track_raw.json and {player name}_song_raw.json''')
  args = parser.parse_args()

  LMSMetadataReader(args.name, args.client, args.ref, args.debug).connect()
