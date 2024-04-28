import googleapiclient.discovery

# YouTube API Key (replace 'YOUR_API_KEY' with your actual API key)
API_KEY = 'AIzaSyAGQUYdZZSnAapY3KzyVcGBJbK13D1t3Yw'

def get_live_chat_id(video_id):
    try:
        # Initialize the YouTube Data API client
        youtube = googleapiclient.discovery.build('youtube', 'v3', developerKey=API_KEY)

        # Request live broadcast details for the specified video ID
        response = youtube.videos().list(
            part='liveStreamingDetails',
            id=video_id
        ).execute()

        # Extract Live Chat ID from the response
        live_chat_id = response['items'][0]['liveStreamingDetails']['activeLiveChatId']

        return live_chat_id

    except googleapiclient.errors.HttpError as e:
        print("An error occurred:", e)
        return None

# Example usage
video_id = 'dLNb8PoXfxM'
live_chat_id = get_live_chat_id(video_id)
print("Live Chat ID:", live_chat_id)
