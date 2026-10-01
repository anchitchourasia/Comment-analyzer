import tkinter as tk
from tkinter import messagebox, scrolledtext
import re
import nltk
import googleapiclient.discovery
from nltk.sentiment import SentimentIntensityAnalyzer

import os
from dotenv import load_dotenv

load_dotenv()

# Initialize NLTK
nltk.download('vader_lexicon')

# YouTube API Key (loaded from environment variable YOUTUBE_API_KEY)
API_KEY = os.environ.get('YOUTUBE_API_KEY', '')

def fetch_video_comments(video_id):
    try:
        # Initialize the YouTube Data API client
        youtube = googleapiclient.discovery.build('youtube', 'v3', developerKey=API_KEY)

        # Request comments for the specified video
        response = youtube.commentThreads().list(
            part='snippet',
            videoId=video_id,
            textFormat='plainText'
        ).execute()

        # Extract comments from the response
        comments = []
        for item in response['items']:
            comment = item['snippet']['topLevelComment']['snippet']['textDisplay']
            comments.append(comment)

        return comments

    except googleapiclient.errors.HttpError as e:
        messagebox.showerror("Error", f"An error occurred: {e}")
        return []

def fetch_live_chat_messages(live_chat_id):
    try:
        # Initialize the YouTube Data API client
        youtube = googleapiclient.discovery.build('youtube', 'v3', developerKey=API_KEY)

        messages = []

        # Request live chat messages for the specified live chat ID
        response = youtube.liveChatMessages().list(
            liveChatId=live_chat_id,
            part='snippet',
            maxResults=100
        ).execute()

        # Extract messages from the response
        for item in response.get('items', []):
            # Check if the message contains text
            if 'snippet' in item and 'textMessageDetails' in item['snippet']:
                message = item['snippet']['textMessageDetails']['messageText']
                messages.append(message)

        return messages

    except googleapiclient.errors.HttpError as e:
        messagebox.showerror("Error", f"An error occurred: {e}")
        return []

def analyze_sentiment(text_list):
    # Initialize the sentiment analyzer
    sia = SentimentIntensityAnalyzer()

    # Analyze sentiment for each text
    sentiment_scores = {'Positive': [], 'Negative': [], 'Neutral': []}
    for text in text_list:
        # Remove special characters and URLs from the text
        clean_text = re.sub(r'http\S+', '', text)
        clean_text = re.sub(r'[^\w\s]', '', clean_text)

        # Perform sentiment analysis
        scores = sia.polarity_scores(clean_text)

        # Categorize the text based on sentiment score
        if scores['compound'] >= 0.05:
            sentiment_scores['Positive'].append((text, scores['compound']))
        elif scores['compound'] <= -0.05:
            sentiment_scores['Negative'].append((text, scores['compound']))
        else:
            sentiment_scores['Neutral'].append((text, scores['compound']))

    return sentiment_scores

def analyze_video():
    video_id = video_id_entry.get()
    if not video_id:
        messagebox.showwarning("Warning", "Please enter a video ID.")
        return

    comments = fetch_video_comments(video_id)
    if not comments:
        return

    sentiment_scores = analyze_sentiment(comments)

    # Display sentiment analysis results
    display_results(sentiment_scores)

def analyze_live_chat():
    live_chat_id = live_chat_id_entry.get()
    if not live_chat_id:
        messagebox.showwarning("Warning", "Please enter a live chat ID.")
        return

    messages = fetch_live_chat_messages(live_chat_id)
    if not messages:
        return

    sentiment_scores = analyze_sentiment(messages)

    # Display sentiment analysis results
    display_results(sentiment_scores)

def display_results(sentiment_scores):
    results_text.delete('1.0', tk.END)
    for sentiment, texts in sentiment_scores.items():
        results_text.insert(tk.END, f"{sentiment}:\n")
        for text, score in texts:
            results_text.insert(tk.END, f"  - {text} (Score: {score})\n")
        results_text.insert(tk.END, "\n")

# GUI
root = tk.Tk()
root.title("YouTube Comment & Live Chat Sentiment Analyzer")

video_id_label = tk.Label(root, text="Enter YouTube Video ID:")
video_id_label.pack()

video_id_entry = tk.Entry(root, width=40)
video_id_entry.pack()

analyze_video_button = tk.Button(root, text="Analyze Video Comments", command=analyze_video)
analyze_video_button.pack()

live_chat_id_label = tk.Label(root, text="Enter Live Chat ID:")
live_chat_id_label.pack()

live_chat_id_entry = tk.Entry(root, width=40)
live_chat_id_entry.pack()

analyze_live_chat_button = tk.Button(root, text="Analyze Live Chat", command=analyze_live_chat)
analyze_live_chat_button.pack()

results_text = scrolledtext.ScrolledText(root, width=80, height=20)
results_text.pack()

root.mainloop()


