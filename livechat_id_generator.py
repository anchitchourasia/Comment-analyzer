import os

import googleapiclient.discovery
from googleapiclient.errors import HttpError


def get_api_key():
    api_key = os.environ.get("YOUTUBE_API_KEY", "")

    if not api_key:
        print(
            "Error: Set the YOUTUBE_API_KEY environment variable."
        )
        return None

    return api_key


def get_live_chat_id(video_id, api_key=None):
    try:
        video_id = video_id.strip()

        if not video_id:
            print("Error: Video ID cannot be empty.")
            return None

        api_key = api_key or get_api_key()

        if not api_key:
            return None

        youtube = googleapiclient.discovery.build(
            "youtube",
            "v3",
            developerKey=api_key
        )

        response = youtube.videos().list(
            part="snippet,liveStreamingDetails",
            id=video_id
        ).execute()

        print("\nAPI response received.")

        if "error" in response:
            print("\nYouTube API returned an error:")
            print(response["error"])
            return None

        items = response.get("items", [])

        if not items:
            print(
                "\nNo video was found. Check the video ID and enter "
                "only the ID, not the complete YouTube URL."
            )
            return None

        video = items[0]

        video_title = video.get(
            "snippet",
            {}
        ).get(
            "title",
            "Unknown video"
        )

        live_streaming_details = video.get(
            "liveStreamingDetails",
            {}
        )

        active_live_chat_id = live_streaming_details.get(
            "activeLiveChatId"
        )

        if not active_live_chat_id:
            print(
                f"\nNo active live chat found for: {video_title}"
            )
            print(
                "The video must be currently live and "
                "live chat must be enabled."
            )
            return None

        return active_live_chat_id

    except HttpError as error:
        print("\nYouTube HTTP error occurred:")
        print(error)

        if getattr(error, "content", None):
            print(
                error.content.decode(
                    "utf-8",
                    errors="replace"
                )
            )

        return None

    except Exception as error:
        print("\nUnexpected error occurred:")
        print(error)
        return None


def get_video_details(video_id, api_key=None):
    """Return dict with live_chat_id, channel_id, channel_title, video_title for a live video."""
    try:
        video_id = video_id.strip()
        if not video_id:
            return None

        api_key = api_key or get_api_key()
        if not api_key:
            return None

        youtube = googleapiclient.discovery.build(
            "youtube", "v3", developerKey=api_key
        )

        response = youtube.videos().list(
            part="snippet,liveStreamingDetails",
            id=video_id
        ).execute()

        items = response.get("items", [])
        if not items:
            return None

        video = items[0]
        snippet = video.get("snippet", {})
        live_streaming_details = video.get("liveStreamingDetails", {})
        active_live_chat_id = live_streaming_details.get("activeLiveChatId")

        if not active_live_chat_id:
            return None

        return {
            "live_chat_id": active_live_chat_id,
            "channel_id": snippet.get("channelId", ""),
            "channel_title": snippet.get("channelTitle", ""),
            "video_title": snippet.get("title", ""),
        }
    except Exception:
        return None



if __name__ == "__main__":
    video_id = input(
        "Enter the active livestream video ID: "
    ).strip()

    live_chat_id = get_live_chat_id(video_id)

    if live_chat_id:
        print("\nLive Chat ID:")
        print(live_chat_id)
    else:
        print("\nLive Chat ID could not be generated.")
