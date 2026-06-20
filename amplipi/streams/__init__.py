# AmpliPi Home Audio
# Copyright (C) 2022 MicroNova LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Digital Audio Streams

Stripped to LMS (Lyrion/squeezelite) only — 2026-06-01
All other stream types (airplay, bluetooth, dlna, fileplayer, fm_radio,
internet_radio, media_device, pandora, plexamp, rca, aux, spotify) removed.
"""

import os
import sys
from typing import List
import logging

from amplipi import models

from .lms import LMS
from .base_streams import *  # pylint: disable=wildcard-import

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
sh = logging.StreamHandler(sys.stdout)
logger.addHandler(sh)

DEBUG = os.environ.get('DEBUG', True)

AnyStream = LMS


def build_stream(stream: models.Stream, mock: bool = False, validate: bool = True) -> AnyStream:
  """ Build an LMS (squeezelite) stream. Only lms type is supported in this build. """
  if stream.type == 'lms':
    args = stream.dict(exclude_none=True)
    args.pop('name')
    disabled = args.pop('disabled', False)
    return LMS(stream.name, args.get('server'), args.get('port'), disabled=disabled, mock=mock)
  raise ValueError(f"Stream type '{stream.type}' is not supported — this build supports lms only")


def stream_types_available() -> List[str]:
  """ Returns the list of available stream types. """
  return [LMS.stream_type]  # type: ignore
