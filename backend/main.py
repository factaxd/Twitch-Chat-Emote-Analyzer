import logging
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from websocket_manager import ConnectionManager
from twitch_irc import start_twitch_bot, stop_twitch_bot, active_bots

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Twitch Chat Analyzer Backend")

# Configure CORS
origins = [
    "http://localhost:5173",  # Default Vite dev server port
    "http://127.0.0.1:5173",
    # Add other frontend origins if needed
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = ConnectionManager()

@app.on_event("startup")
async def startup_event():
    logger.info("Starting FastAPI application...")
    
    # Confirm that emoji sentiment scores are loaded
    try:
        from nlp_processor import emote_sentiment_scores
        logger.info(f"Loaded {len(emote_sentiment_scores)} emoji sentiment scores from emoji_sentiment_scores.csv for keyword analysis")
    except ImportError:
        logger.warning("Failed to import emote_sentiment_scores from nlp_processor")
    
    # Perform any other startup tasks here if needed

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down FastAPI application...")
    streamer_names = list(active_bots.keys()) # Get keys before iterating
    logger.info(f"Stopping {len(streamer_names)} active Twitch bots...")
    shutdown_tasks = [stop_twitch_bot(name) for name in streamer_names]
    await asyncio.gather(*shutdown_tasks) # Run shutdowns concurrently
    logger.info("All Twitch bots stopped.")

@app.get("/")
async def read_root():
    return {"message": "Twitch Chat Analyzer Backend is running"}

@app.get("/status")
async def get_status():
    active_streamers = list(active_bots.keys())
    return {
        "message": "Twitch Chat Analyzer Backend Status",
        "active_analysis_count": len(active_streamers),
        "analyzing_streamers": active_streamers
    }

@app.post("/reload-emoji-sentiments")
async def reload_emoji_sentiments():
    """Reloads emoji sentiment scores from the CSV file without restarting the server."""
    try:
        from nlp_processor import reload_emote_sentiment_scores
        emote_count = reload_emote_sentiment_scores()
        return {
            "message": f"Successfully reloaded {emote_count} emoji sentiment scores",
            "success": True,
            "emote_count": emote_count
        }
    except Exception as e:
        logger.error(f"Error reloading emoji sentiment scores: {e}")
        return {
            "message": f"Failed to reload emoji sentiment scores: {e}",
            "success": False,
            "emote_count": 0
        }

@app.websocket("/ws/{streamer_name}")
async def websocket_endpoint(websocket: WebSocket, streamer_name: str):
    streamer_name = streamer_name.lower().strip()
    if not streamer_name:
        logger.warning("WebSocket connection attempt with empty streamer name.")
        await websocket.close(code=1008) # Policy Violation
        return

    await manager.connect(websocket, streamer_name)
    logger.info(f"WebSocket client connected for streamer: {streamer_name}")

    try:
        # Pass the connection manager to the bot starter
        bot_instance = await start_twitch_bot(streamer_name, manager)
        if bot_instance:
            logger.info(f"Twitch bot is running or was started for {streamer_name}")
            # Optionally send confirmation back to the specific client
            # await websocket.send_json({"type": "status", "payload": f"Connected to analysis for {streamer_name}"})
        else:
            # Handle case where bot failed to start (e.g., auth error)
            logger.error(f"Failed to ensure Twitch bot is running for {streamer_name}")
            # Error message should have been broadcast by start_twitch_bot
            # Consider closing the websocket connection if the bot is essential
            # await websocket.close(code=1011) # Internal Error
            pass # Keep connection open for now, error was broadcast

    except Exception as e:
        logger.error(f"Error starting Twitch bot for {streamer_name}: {e}", exc_info=True)
        await manager.broadcast_to_streamer(streamer_name, {"type": "error", "payload": f"Server error starting analysis: {e}"})
        # Optionally close connection
        # await websocket.close(code=1011)

    try:
        while True:
            # Keep the connection alive. Handle client messages if needed.
            # Example: data = await websocket.receive_text()
            # Currently, we primarily push data, so just wait for disconnect.
            await asyncio.sleep(3600) # Sleep for a long time to keep connection open
            # Or use: await websocket.receive_text() # If you expect client messages

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected by client for streamer: {streamer_name}")
    except Exception as e:
        # Log unexpected errors during the connection lifetime
        logger.error(f"WebSocket error for {streamer_name}: {e}", exc_info=True)
    finally:
        logger.info(f"Cleaning up WebSocket connection for {streamer_name}")
        await manager.disconnect(websocket, streamer_name)
        if streamer_name not in manager.active_connections:
            logger.info(f"Last client disconnected for {streamer_name}. Requesting bot stop.")
            try:
                stopped = await stop_twitch_bot(streamer_name)
                if stopped:
                    logger.info(f"Successfully stopped Twitch bot for {streamer_name}.")
                else:
                     logger.warning(f"Attempted to stop bot for {streamer_name}, but it wasn't found (might have already stopped).")
            except Exception as e:
                logger.error(f"Error stopping Twitch bot for {streamer_name} on disconnect: {e}", exc_info=True)
        else:
            logger.info(f"Other clients still connected for {streamer_name}. Bot remains active.")

if __name__ == "__main__":
    print("Please run using: uvicorn main:app --reload --port 8000")
    # Note: Use `uvicorn main:app --reload --port 8000` to run for development
    pass