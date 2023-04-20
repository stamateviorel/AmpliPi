#!/usr/bin/python3
"""LMS Metadata"""

import argparse
import fcntl
import json
import time
import requests
from typing import Optional

class LMSMetadataReader:
  """A class for getting metadata from a Logitech Media Server."""

  # meta_ref is probably an unneccessary variable to pass as an arg since it's obscured from the user, but we can eventually make it an optional setting for the user
  def __init__(self, name: str, meta_ref: Optional[int] = 2, dump: Optional[bool] = False):
    self.player_name = name
    self.IP = None
    self.meta_ref_rate = meta_ref
    self.connected = False
    self.dump = dump

  def connect(self):
    """Discovers LMS Player and then requests metadata repetitively"""
    f = open(f"lms_{str(self.player_name).replace(' ', '_')}_metadata.json", 'wt', encoding='utf-8')
    json.dump({'track': 'Loading...', 'artist': 'Loading...', 'album': 'Loading...', 'image_url': 'static/imgs/lms.png'}, f, indent = 2)
    f.close()
    x = 0
    # Loops through all available IPS, making requests to check for LMS Clients
    # Originally this used a port scanner, but LMS servers aren't visible to port scanners by default so it ended up just brute force scanning all IPS regardless
    # The request time gets longer each time in case the server is laggy, but it goes quick initally so that the scan takes the least amount of time
    reqtime = 0.001
    while self.IP is None:
      if x > 256:
        x = 0
        if reqtime < 10:
          reqtime = reqtime * 10
        else:
          reqtime = 0.001
      try:
        # You can use the player name in place of the MAC address for all LMS requests, this one just asks if the ip has a running player of a given name
        # It checks by name just so that you don't get the wrong metadata in cases where you have multiple LMS Streams on a single device
        track_json = {"id": 1, "method": "slim.request", "params": [ self.player_name, ["status", "-",100] ]}
        track_info = requests.post(f'http://192.168.0.{x}:9000/jsonrpc.js 2>/dev/null', json=track_json, timeout=reqtime)
        track_load = json.loads(track_info.text)
        stream_name = track_load['result']['player_name']
        if self.player_name == stream_name:
          self.IP = f"192.168.0.{x}"
      except:
        x+=1

    # When not connected, search for player to connect to by the proper name
    while not self.connected:
      try:
        player_json = {"id": 1,	"method": "slim.request",	"params": [self.player_name, ["players", "-", 100, "playerid"]]}
        player_info = requests.get(f'http://{self.IP}:9000/jsonrpc.js', json=player_json, timeout=10)
        player_load = json.loads(player_info.text)
        players = player_load['result']['players_loop']

        for player in players:
          connected = player['connected']
          if connected and player['name'] == self.player_name:
            self.connected = True
          else:
            time.sleep(0.1)
      except:
        # When first creating an LMS stream, there can be random errors that will close the while loop
        # typically when asking the player for info when there isn't a player linked to the stream yet
        pass

    while self.connected:
      try:
        track_json = {"id": 1, "method": "slim.request", "params": [ self.player_name, ["status", "-",100] ]}
        track_info = requests.post(f'http://{self.IP}:9000/jsonrpc.js 2>/dev/null', json=track_json, timeout=200)
        track_load = json.loads(track_info.text)

        track_id = track_load["result"]["playlist_loop"][0]["id"]
        song_json = {"id":2,"method":"slim.request","params":[ self.player_name, ["songinfo","-",100,f"track_id:{track_id}"]]}
        song_info = requests.post(f'http://{self.IP}:9000/jsonrpc.js 2>/dev/null', json=song_json, timeout=200)
        song_load = json.loads(song_info.text)
      except:
        print(f"KeyError, trying again in {self.meta_ref_rate} seconds...")

      x = 0
      song_data = {}
      for item in song_load["result"]["songinfo_loop"]:
        for info in item:
          song_data[info] = song_load['result']['songinfo_loop'][x][info]
        x += 1

      x = 0
      track_data = {}
      for item in track_load["result"]["playlist_loop"]:
        for info in item:
          track_data[info] = track_load['result']['playlist_loop'][x][info]
        x += 1

      meta = {
        'track': 'Loading...',
        'artist': 'Loading...',
        'album': 'Loading...',
        'image_url': 'static/imgs/lms.png'
       }

      if song_data['type'] == "MP3 Radio" or song_data['type'] == "AAC Radio" or song_data['type'] == "Radio" or song_data['type'] == "TEXT/X-JSON Radio":
        try:
          meta["track"] = track_data["title"]
          meta['artist'] = None
          meta['album'] = song_data['remote_title']
          meta["image_url"] = f"http://{self.IP}:9000/music/{song_data['coverid']}/cover.jpg?id={song_data['coverid']}"
        except KeyError:
          # Sometimes, KeyError will occur when switching from pandora to a different stream type since the json that LMS sends is formatted differently
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
          # Sometimes, KeyError will occur when switching to pandora from a different stream type since the json that LMS sends is formatted differently
          print(f"KeyError, trying again in {self.meta_ref_rate} seconds...")

          meta["track"] = song_data["title"]
          meta["image_url"] = song_data["artwork_url"]
      # File locking so to reduce errors, without locks here and on the read cycle you can sometimes read while writing, which will read an empty file and crash the stream
      f = open(f"lms_{str(self.player_name).replace(' ', '_')}_metadata.json", 'wt', encoding='utf-8')
      try:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(meta, f, indent = 2)
      finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()

      if self.dump:
        f = open(f"{str(self.player_name).replace(' ', '_')}_track_raw.json", "w")
        json.dump(track_load, f, indent = 2)
        f.close()
        f = open(f"{str(self.player_name).replace(' ', '_')}_song_raw.json", "w")
        json.dump(song_load, f, indent = 2)
        f.close()

      # a sleep equal to the meta_ref_rate, that way the metadata refreshes on a set schedule while looping instead of just doing it at all times always
      time.sleep(self.meta_ref_rate)

if __name__ == '__main__':
  parser = argparse.ArgumentParser(description='LMS Metadata')
  parser.add_argument('--name', type=str, required=True, help='The name of the LMS Player')
  parser.add_argument('--ref', type=int, default=2, help='The frequency of metadata refresh cycles')
  parser.add_argument('--dump', action='store_true', help="""Create raw json dumps directly from the LMS server,
                      creates two files, {player name}_track_raw.json and {player name}_song_raw.json in the main directory""")
  args = parser.parse_args()

  LMSMetadataReader(args.name, args.ref, args.dump).connect()
