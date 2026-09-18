import logging
from app.tools.base import BaseTool
from app.tools.music.provider import (
    trigger_media_key, 
    VK_MEDIA_PLAY_PAUSE, 
    VK_MEDIA_NEXT_TRACK, 
    VK_MEDIA_PREV_TRACK, 
    VK_MEDIA_STOP
)
from app.tools.music.youtube_provider import YouTubeMusicProvider
from app.tools.music.spotify_provider import SpotifyProvider

logger = logging.getLogger(__name__)

class MusicPlayTool(BaseTool):
    name = "music_play"
    description = "Searches for and plays music tracks, artists, or albums."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The song, artist, or album to play."},
            "service": {
                "type": "string", 
                "enum": ["youtube_music", "spotify"], 
                "description": "The music streaming service to use. Defaults to youtube_music.", 
                "default": "youtube_music"
            }
        },
        "required": ["query"]
    }

    async def execute(self, args: dict) -> str:
        query = args.get("query")
        service = args.get("service", "youtube_music")
        
        if service == "spotify":
            return await SpotifyProvider.play(query)
        else:
            return await YouTubeMusicProvider.play(query)

class MusicPauseTool(BaseTool):
    name = "music_pause"
    description = "Pauses the currently playing music."
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        trigger_media_key(VK_MEDIA_PLAY_PAUSE)
        return "Music playback paused."

class MusicResumeTool(BaseTool):
    name = "music_resume"
    description = "Resumes the currently paused music."
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        # The play/pause key toggles the state universally
        trigger_media_key(VK_MEDIA_PLAY_PAUSE)
        return "Music playback resumed."

class MusicStopTool(BaseTool):
    name = "music_stop"
    description = "Stops the currently playing music entirely."
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        trigger_media_key(VK_MEDIA_STOP)
        return "Music playback stopped."

class MusicNextTrackTool(BaseTool):
    name = "music_next_track"
    description = "Skips to the next music track."
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        trigger_media_key(VK_MEDIA_NEXT_TRACK)
        return "Skipped to the next track."

class MusicPreviousTrackTool(BaseTool):
    name = "music_previous_track"
    description = "Goes back to the previous music track."
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        trigger_media_key(VK_MEDIA_PREV_TRACK)
        return "Returned to the previous track."