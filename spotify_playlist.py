#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "spotipy>=2.24.0",
#     "requests>=2.32.3",
#     "click>=8.1.7",
#     "python-dotenv>=1.0.1",
#     "pillow>=10.4.0",
#     "rich>=13.7.1",
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
from rich.progress import (
    Progress,
    BarColumn,
    TextColumn,
    TimeElapsedColumn,
    SpinnerColumn,
)
from rich.console import Console
import random


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
    level=logging.WARNING, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
# Suppress specific spotipy informational logs if they become too noisy
# logging.getLogger("spotipy.client").setLevel(logging.WARNING)
# logging.getLogger("spotipy.oauth2").setLevel(logging.WARNING)


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
) -> int:
    new_tracks = [
        track["id"] for track in tracks if track["id"] not in existing_track_ids
    ]
    if new_tracks:
        for i in range(0, len(new_tracks), 100):
            sp.playlist_add_items(playlist_id, new_tracks[i : i + 100])
        logger.info(f"Added {len(new_tracks)} new tracks to playlist ID: {playlist_id}")
        return len(new_tracks)
    else:
        logger.info(f"No new tracks to add to playlist ID: {playlist_id}")
        return -1


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
                artist_name = playlist["name"][: -len(" Discography")]
                if artist_name:  # Ensure we don't add empty names
                    artist_names.append(artist_name)
                    logger.info(f"Found discography playlist for: {artist_name}")
        playlists = sp.next(playlists) if playlists["next"] else None
    if not artist_names:
        logger.info("No discography playlists found to update.")
    return artist_names


@click.command()
@click.argument("artist_names", nargs=-1)  # Accept multiple artist names
@click.option(
    "--log-level",
    default="WARNING",
    type=click.Choice(
        ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], case_sensitive=False
    ),
    help="Set the logging level for the standard Python logger.",
)
def create_artist_playlist(artist_names: Tuple[str], log_level: str) -> None:
    # Set the Python logging level based on the command-line option
    numeric_level = getattr(logging, log_level.upper(), None)
    if isinstance(numeric_level, int):
        logging.getLogger().setLevel(numeric_level)
        # Optionally, you could also inform the user if the level is very verbose
        if numeric_level <= logging.DEBUG:
            # Using rich console for this one-off, non-loop message
            # We only print this if it's not the default, to avoid noise.
            # However, current default is WARNING, so DEBUG/INFO will trigger this.
            # Consider if this message is always wanted or only if different from script default.
            if (
                log_level.upper() != "WARNING"
            ):  # Assuming WARNING is the script's default base
                Console().print(
                    f"[dim]Standard Python logger set to {log_level.upper()}[/dim]"
                )
    else:
        # This path should ideally not be reached due to click.Choice validation
        logging.warning(f"Invalid log level: {log_level}. Using default.")

    sp = authenticate_spotify()
    user_id = sp.me()["id"]

    processed_artist_names = list(artist_names)

    if not processed_artist_names:
        # Use Rich console for initial messages
        console = Console()
        console.print(
            "No artist names provided. Attempting to update all existing discography playlists."
        )
        processed_artist_names = get_all_user_discography_artists(sp, user_id)
        if not processed_artist_names:
            console.print("No discography playlists found to update. Exiting.")
            return

    random.shuffle(processed_artist_names)

    # Print initial count here, before Progress context manager
    console = Console()  # Re-initialize or ensure it's available
    console.print(f"Found {len(processed_artist_names)} artists to process.")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
    ) as progress:
        overall_task_description = f"Updating {len(processed_artist_names)} artists"
        overall_task = progress.add_task(
            overall_task_description, total=len(processed_artist_names)
        )

        for i, artist_name in enumerate(processed_artist_names):
            artist_task_description_template = f"{artist_name}"
            # Define max length for step descriptions for padding
            max_step_desc_len = 30  # Adjust as needed

            artist_task = progress.add_task(
                f"{artist_task_description_template} ...", total=7, start=False
            )

            try:
                step_desc = "Getting artist info".ljust(max_step_desc_len)
                progress.update(
                    artist_task,
                    description=f"[{artist_task_description_template}] {step_desc}",
                    visible=True,
                )
                progress.start_task(artist_task)
                artist_id, artist_image = get_artist_info(sp, artist_name)
                progress.update(artist_task, advance=1)

                if artist_id is None:
                    progress.console.print(f"❌ Artist '{artist_name}' not found.")
                    progress.update(
                        artist_task, completed=7, visible=False
                    )  # Mark as complete and hide
                    continue

                playlist_name = f"{artist_name} Discography"
                step_desc = "Finding playlist".ljust(max_step_desc_len)
                progress.update(
                    artist_task,
                    description=f"[{artist_task_description_template}] {step_desc}",
                )
                playlist_id = find_playlist(sp, user_id, playlist_name)
                progress.update(artist_task, advance=1)

                step_desc = "Getting all songs".ljust(max_step_desc_len)
                progress.update(
                    artist_task,
                    description=f"[{artist_task_description_template}] {step_desc}",
                )
                tracks = get_all_songs(sp, artist_id)
                progress.update(artist_task, advance=1)

                added_tracks_count = 0
                if playlist_id:
                    step_desc = "Getting existing tracks".ljust(max_step_desc_len)
                    progress.update(
                        artist_task,
                        description=f"[{artist_task_description_template}] {step_desc}",
                    )
                    existing_track_ids = get_playlist_tracks(sp, playlist_id)
                    progress.update(artist_task, advance=1)

                    step_desc = "Adding new tracks".ljust(max_step_desc_len)
                    progress.update(
                        artist_task,
                        description=f"[{artist_task_description_template}] {step_desc}",
                    )
                    added_tracks_count = add_tracks_to_playlist(
                        sp, playlist_id, tracks, existing_track_ids
                    )
                    progress.update(artist_task, advance=1)
                else:
                    step_desc = "Creating playlist".ljust(max_step_desc_len)
                    progress.update(
                        artist_task,
                        description=f"[{artist_task_description_template}] {step_desc}",
                    )
                    playlist_id = create_playlist(sp, user_id, playlist_name)
                    progress.update(artist_task, advance=1)

                    step_desc = "Adding tracks".ljust(max_step_desc_len)
                    progress.update(
                        artist_task,
                        description=f"[{artist_task_description_template}] {step_desc}",
                    )
                    added_tracks_count = add_tracks_to_playlist(
                        sp, playlist_id, tracks, []
                    )
                    progress.update(artist_task, advance=1)

                if artist_image:
                    step_desc = "Downloading cover image".ljust(max_step_desc_len)
                    progress.update(
                        artist_task,
                        description=f"[{artist_task_description_template}] {step_desc}",
                    )
                    image_data = download_image(artist_image)
                    progress.update(artist_task, advance=1)
                    if image_data:
                        step_desc = "Setting cover image".ljust(max_step_desc_len)
                        progress.update(
                            artist_task,
                            description=f"[{artist_task_description_template}] {step_desc}",
                        )
                        set_playlist_cover_image(sp, playlist_id, image_data)
                        progress.update(artist_task, advance=1)
                    else:
                        progress.console.print(
                            f"⚠️ Could not download cover image for {artist_name}."
                        )
                        progress.update(
                            artist_task, advance=1
                        )  # Advance for the failed download
                        progress.update(
                            artist_task, advance=1
                        )  # Advance for skipping set_playlist_cover_image
                else:
                    progress.update(
                        artist_task, advance=1
                    )  # Advance for skipping download
                    progress.update(
                        artist_task, advance=1
                    )  # Advance for skipping set_playlist_cover_image

                # Construct success message based on added_tracks_count
                if added_tracks_count > 0:
                    message = f'Added {added_tracks_count} tracks to "{playlist_name}".'
                elif added_tracks_count == 0:
                    message = (
                        f'No new tracks for "{playlist_name}". Playlist is up to date.'
                    )
                else:  # handles -1 for existing playlist with no new tracks to add, or other cases
                    message = f'Playlist "{playlist_name}" processed.'

                progress.console.print(
                    f"✅ [{i+1}/{len(processed_artist_names)}] {message}"
                )
                progress.update(artist_task, visible=False)  # Hide completed task

            except Exception as e:
                progress.console.print(
                    f"❌ [{i+1}/{len(processed_artist_names)}] Error processing '{artist_name}': {e}"
                )
                progress.update(artist_task, visible=False)  # Hide task on error
            finally:
                progress.update(overall_task, advance=1)


if __name__ == "__main__":
    create_artist_playlist()
