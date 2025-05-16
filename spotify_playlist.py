#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "spotipy>=2.24.0",
#     "requests>=2.32.3",
#     "click>=8.1.7",
#     "python-dotenv>=1.0.1",
#     "pillow>=10.4.0",
# ]
# ///
import click
import requests
import base64
import logging
from typing import Tuple, Optional, List, Dict, Any
from io import BytesIO
from PIL import Image
import os
import spotipy
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv


def authenticate_spotify() -> Spotify:
    load_dotenv()
    sp = spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=os.getenv("SPOTIFY_CLIENT_ID"),
            client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
            redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
            scope="playlist-modify-public playlist-read-private playlist-modify-private ugc-image-upload",
        )
    )
    return sp


# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_artist_info(
    sp: Spotify, artist_name: str
) -> Tuple[Optional[str], Optional[str]]:
    results = sp.search(q="artist:" + artist_name, type="artist")
    items = results["artists"]["items"]
    if len(items) > 0:
        artist = items[0]
        artist_id = artist["id"]
        artist_image = artist["images"][0]["url"] if artist["images"] else None
        logger.info(f"Found artist: {artist_name} (ID: {artist_id})")
        return artist_id, artist_image
    else:
        logger.warning(f"Artist '{artist_name}' not found.")
        return None, None


def get_all_songs(sp: Spotify, artist_id: str) -> List[Dict[str, Any]]:
    all_tracks = []

    albums = sp.artist_albums(artist_id, album_type="album,single,compilation")
    albums = albums["items"]

    for album in albums:
        tracks = sp.album_tracks(album["id"])["items"]
        for track in tracks:
            track_info = {
                "name": track["name"],
                "id": track["id"],
                "release_date": album["release_date"],
            }
            all_tracks.append(track_info)

    all_tracks.sort(key=lambda x: x["release_date"])
    logger.info(f"Collected {len(all_tracks)} tracks for artist ID: {artist_id}")

    return all_tracks


def find_playlist(sp: Spotify, user_id: str, playlist_name: str) -> Optional[str]:
    playlists = sp.user_playlists(user_id)
    while playlists:
        for playlist in playlists["items"]:
            if playlist["name"] == playlist_name:
                logger.info(
                    f"Found existing playlist: {playlist_name} (ID: {playlist['id']})"
                )
                return playlist["id"]
        playlists = sp.next(playlists) if playlists["next"] else None
    logger.info(f"No existing playlist found with name: {playlist_name}")
    return None


def get_playlist_tracks(sp: Spotify, playlist_id: str) -> List[str]:
    tracks = []
    results = sp.playlist_tracks(playlist_id)
    while results:
        tracks.extend([item["track"]["id"] for item in results["items"]])
        results = sp.next(results) if results["next"] else None
    logger.info(f"Retrieved {len(tracks)} tracks from playlist ID: {playlist_id}")
    return tracks


def create_playlist(sp: Spotify, user_id: str, playlist_name: str) -> str:
    playlist = sp.user_playlist_create(user_id, playlist_name, public=True)
    logger.info(f"Created new playlist '{playlist_name}' (ID: {playlist['id']})")
    return playlist["id"]


def add_tracks_to_playlist(
    sp: Spotify,
    playlist_id: str,
    tracks: List[Dict[str, Any]],
    existing_track_ids: List[str],
) -> None:
    new_tracks = [
        track["id"] for track in tracks if track["id"] not in existing_track_ids
    ]
    if new_tracks:
        for i in range(0, len(new_tracks), 100):
            sp.playlist_add_items(playlist_id, new_tracks[i : i + 100])
        logger.info(f"Added {len(new_tracks)} new tracks to playlist ID: {playlist_id}")
    else:
        logger.info(f"No new tracks to add to playlist ID: {playlist_id}")


def download_image(image_url: str) -> Optional[BytesIO]:
    response = requests.get(image_url)
    if response.status_code == 200:
        logger.info(f"Downloaded image from {image_url}")
        return BytesIO(response.content)
    else:
        logger.error(f"Failed to download image from {image_url}")
        return None


def set_playlist_cover_image(
    sp: Spotify, playlist_id: str, image_data: BytesIO
) -> None:
    image = Image.open(image_data)
    image = image.resize((640, 640))

    buffered = BytesIO()
    image.save(buffered, format="JPEG")
    img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")

    sp.playlist_upload_cover_image(playlist_id, img_str)
    logger.info(f"Set cover image for playlist ID: {playlist_id}")


def get_all_user_discography_artists(sp: Spotify, user_id: str) -> List[str]:
    """
    Retrieves all artist names from the user's playlists that match the
    "{artist_name} Discography" naming convention.
    """
    artist_names = []
    playlists = sp.user_playlists(user_id)
    while playlists:
        for playlist in playlists["items"]:
            if playlist["name"].endswith(" Discography"):
                # Extract artist name from "Artist Name Discography"
                artist_name = playlist["name"][:-len(" Discography")]
                if artist_name: # Ensure we don't add empty names
                    artist_names.append(artist_name)
                    logger.info(f"Found discography playlist for: {artist_name}")
        playlists = sp.next(playlists) if playlists["next"] else None
    if not artist_names:
        logger.info("No discography playlists found to update.")
    return artist_names


@click.command()
@click.argument("artist_names", nargs=-1)  # Accept multiple artist names
def create_artist_playlist(artist_names: Tuple[str]) -> None:
    sp = authenticate_spotify()
    user_id = sp.me()["id"]

    processed_artist_names = list(artist_names)

    if not processed_artist_names:
        logger.info("No artist names provided. Attempting to update all existing discography playlists.")
        processed_artist_names = get_all_user_discography_artists(sp, user_id)
        if not processed_artist_names:
            logger.info("No discography playlists found to update. Exiting.")
            return

    for artist_name in processed_artist_names:
        try:
            artist_id, artist_image = get_artist_info(sp, artist_name)
            if artist_id is None:
                logger.error(
                    f"Failed to create playlist. Artist '{artist_name}' not found."
                )
                continue

            playlist_name = f"{artist_name} Discography"
            playlist_id = find_playlist(sp, user_id, playlist_name)

            tracks = get_all_songs(sp, artist_id)

            if playlist_id:
                existing_track_ids = get_playlist_tracks(sp, playlist_id)
                add_tracks_to_playlist(sp, playlist_id, tracks, existing_track_ids)
            else:
                playlist_id = create_playlist(sp, user_id, playlist_name)
                add_tracks_to_playlist(sp, playlist_id, tracks, [])

            if artist_image:
                image_data = download_image(artist_image)
                if image_data:
                    set_playlist_cover_image(sp, playlist_id, image_data)

            logger.info(f"Playlist '{playlist_name}' created/updated successfully.")
        except Exception as e:
            logger.error(
                f"An error occurred while processing artist '{artist_name}': {e}"
            )


if __name__ == "__main__":
    create_artist_playlist()
