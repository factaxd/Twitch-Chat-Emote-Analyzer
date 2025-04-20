# Twitch Chat Real-Time Analyzer

A real-time analytics application designed to capture and process Twitch IRC chat messages, identifying viewer engagement patterns and providing insights to optimize streamer interactions.

## Features

*   **Real-Time Chat Capture:** Connects to Twitch IRC to capture chat messages as they happen.
*   **Asynchronous Processing:** Utilizes an asynchronous pipeline for efficient handling of incoming messages.
*   **NLP Analysis:**
    *   **Sentiment Analysis:** Analyzes the sentiment (positive, negative, neutral) of chat messages using NLTK.
    *   **Keyword Extraction:** Identifies frequently used keywords and topics in the chat.
*   **Emote Analysis:**
    *   Detects standard Twitch emotes, FFZ, and 7TV emotes within messages.
    *   Analyzes emote usage frequency and sentiment (based on a custom dataset).
*   **Real-Time Dashboard:** (Planned) A web-based dashboard (using React and WebSockets) to visualize:
    *   Overall chat sentiment trends over time.
    *   Top keywords and their frequency.
    *   Most used emotes and their sentiment scores.
    *   Viewer engagement metrics.
*   **Alerts:** (Planned) Configurable alerts for significant shifts in chat sentiment, specific keyword usage spikes, or unusual activity patterns.
*   **Streamer Input UI:** A simple interface (in the frontend) for the streamer to input the target Twitch channel and start/stop the analysis.

## Project Structure

*   `backend/`: Contains the Python FastAPI application responsible for:
    *   Connecting to Twitch IRC (`twitch_irc.py`).
    *   Processing messages (NLP: `nlp_processor.py`, Emotes: `emote_handler.py`).
    *   Managing WebSocket connections for real-time frontend updates (`websocket_manager.py`).
    *   The main application logic (`main.py`).
*   `frontend/`: Contains the React application for the user interface and dashboard.
    *   Displays real-time analytics received via WebSockets.
    *   Provides controls for starting/stopping analysis.
*   `emoji_sentiment_scores.csv`: A custom dataset mapping 7TV emotes to sentiment scores. *(See Note below)*
*   `.gitignore`: Specifies intentionally untracked files that Git should ignore.
*   `requirements.txt`: Lists the Python dependencies for the backend.
*   `README.md`: This file.

## Setup

**Prerequisites:**

*   Python 3.8+
*   Node.js and npm (or yarn)

**Backend:**

```bash
# Navigate to the backend directory
cd backend

# Create and activate a virtual environment (recommended)
python -m venv venv
# Windows Powershell:
.\venv\Scripts\Activate.ps1
# Bash/Zsh:
# source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Download necessary NLTK data models
python -m nltk.downloader -d ./nltk_data punkt averaged_perceptron_tagger stopwords wordnet omw-1.4

# Create a .env file based on .env.example (if provided)
# and add your Twitch credentials (Username, OAuth Token)
# Example .env:
# TWITCH_USERNAME="your_bot_username"
# TWITCH_OAUTH_TOKEN="oauth:your_oauth_token"
# TARGET_CHANNEL="target_streamer_channel"
# CLIENT_ID="your_client_id"        # Optional: Needed for some API calls if implemented
# CLIENT_SECRET="your_client_secret" # Optional: Needed for some API calls if implemented
# OPENAI_API_KEY="your_openai_key"    # If using OpenAI for advanced NLP

# Run the backend server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend:**

```bash
# Navigate to the frontend directory
cd frontend

# Install Node.js dependencies
npm install
# or: yarn install

# Run the frontend development server
npm run dev
# or: yarn dev

# The frontend will typically be available at http://localhost:5173
```

## Technology Stack

*   **Backend:** Python, FastAPI, Uvicorn, `websockets`, NLTK, `python-dotenv`
*   **Frontend:** React, TypeScript, Vite, Socket.IO Client (or native WebSocket API)
*   **Real-time Communication:** WebSockets
*   **NLP:** NLTK (Natural Language Toolkit)

## Note on `emoji_sentiment_scores.csv`

This project utilizes a custom dataset (`emoji_sentiment_scores.csv`) to assign sentiment scores to specific 7TV emotes.
