import os
import asyncio
import logging
from twitchio.ext import commands
from twitchio.errors import AuthenticationError
from dotenv import load_dotenv
from typing import Set, Optional, List, Dict

from websocket_manager import ConnectionManager
# Import NLP functions
from nlp_processor import analyze_sentiment, extract_keywords
# Import emote handler and new type
from emote_handler import fetch_all_emotes_for_channel, detect_emotes_in_message, EmoteSet, EmoteData
# Import emote sentiment scores, if available
try:
    from nlp_processor import emote_sentiment_scores
except ImportError:
    emote_sentiment_scores = {}

# Load environment variables for Twitch credentials
load_dotenv()

TWITCH_ACCESS_TOKEN = os.getenv("TWITCH_ACCESS_TOKEN", "")
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "")
BOT_NICKNAME = os.getenv("BOT_NICKNAME", "justinfan123") # Use an anonymous user if no specific bot account

logger = logging.getLogger(__name__)

class TwitchBot(commands.Bot):
    def __init__(self, streamer_channel: str, ws_manager: ConnectionManager):
        self.streamer_channel = streamer_channel.lower()
        self.ws_manager = ws_manager
        # Store emotes as dictionaries {name: url}
        self.ffz_emotes: EmoteSet = {}
        self.seventv_channel_emotes: EmoteSet = {}
        self.seventv_global_emotes: EmoteSet = {}
        self._emote_fetch_task: Optional[asyncio.Task] = None
        
        # Import and store emote sentiment scores
        try:
            self.emote_sentiment_scores = emote_sentiment_scores
            logger.info(f"Loaded {len(self.emote_sentiment_scores)} emote sentiment scores for TwitchBot {streamer_channel}")
        except Exception as e:
            logger.error(f"Failed to load emote sentiment scores: {e}")
            self.emote_sentiment_scores = {}

        # Initialize the bot with credentials and the channel to join
        # Use anonymous login if no token is provided
        irc_token = TWITCH_ACCESS_TOKEN if TWITCH_ACCESS_TOKEN else None
        nick = BOT_NICKNAME if not irc_token else None # twitchio handles nick from token if provided

        super().__init__(
            token=irc_token,
            client_id=TWITCH_CLIENT_ID,
            nick=nick,
            prefix='!thisprefixisunused', # Required, but we don't use commands
            initial_channels=[self.streamer_channel]
        )
        logger.info(f"TwitchBot initialized for channel: {self.streamer_channel}")

    async def event_ready(self):
        logger.info(f'Logged into Twitch IRC as | {self.nick} for channel {self.streamer_channel}')
        # Start fetching emotes in the background once connected
        if self._emote_fetch_task is None or self._emote_fetch_task.done():
             logger.info(f"Creating emote fetch task for {self.streamer_channel}")
             self._emote_fetch_task = asyncio.create_task(
                 self._fetch_emotes(),
                 name=f"EmoteFetch-{self.streamer_channel}"
             )
        else:
             logger.warning(f"Emote fetch task for {self.streamer_channel} already running.")

        await self.ws_manager.broadcast_to_streamer(
            self.streamer_channel,
            {"type": "status", "payload": f"Successfully joined chat for {self.streamer_channel}"}
        )

    async def _fetch_emotes(self):
        """Internal task to fetch emotes and store them.
           Runs in the background after connection is ready.
        """
        logger.info(f"Starting emote fetch for {self.streamer_channel}...")
        try:
            # Pass client_id and token from environment for Twitch API call
            ffz, tv_chan, tv_glob = await fetch_all_emotes_for_channel(
                self.streamer_channel,
                TWITCH_CLIENT_ID, # Fetched from .env
                TWITCH_ACCESS_TOKEN # Fetched from .env
            )
            self.ffz_emotes = ffz
            self.seventv_channel_emotes = tv_chan
            self.seventv_global_emotes = tv_glob # Store the global set reference
            logger.info(f"Successfully fetched emotes for {self.streamer_channel}: FFZ({len(ffz)}), 7TV({len(tv_chan)}), 7TV_Global({len(tv_glob)})")
            # Optionally notify clients that emotes are loaded
            await self.ws_manager.broadcast_to_streamer(
                 self.streamer_channel,
                 {"type": "status", "payload": "FFZ/7TV emote data loaded."}
            )
        except Exception as e:
            logger.error(f"Error in _fetch_emotes task for {self.streamer_channel}: {e}", exc_info=True)
            await self.ws_manager.broadcast_to_streamer(
                 self.streamer_channel,
                 {"type": "error", "payload": "Failed to load FFZ/7TV emote data."}
            )

    async def event_message(self, message):
        # Ignore messages from the bot itself if not using anonymous login
        if message.echo:
            return

        # Ensure message content exists
        if not message.content:
             return

        # Log the raw message content
        logger.debug(f"#{message.channel.name} - {message.author.name}: {message.content}")

        # --- Data Processing Pipeline --- 
        # Analyze sentiment (now returns score and word details)
        # Use a placeholder if analyze_sentiment fails
        sentiment_score: Optional[float] = None
        sentiment_words: Dict[str, float] = {}
        try:
            sentiment_score, sentiment_words = analyze_sentiment(message.content)
        except Exception as e:
            logger.error(f"Error calling analyze_sentiment for '{message.content[:50]}...': {e}")
            sentiment_score = 0.0 # Default to neutral on error
            sentiment_words = {}

        # Extract keywords
        keywords = extract_keywords(message.content)

        # --- Enhanced Emote Processing --- 
        # Detect FFZ/7TV/BTTV emotes
        all_custom_emotes: List[EmoteData] = detect_emotes_in_message(
            message.content,
            self.ffz_emotes,
            self.seventv_channel_emotes,
            self.seventv_global_emotes
        )

        # Prepare combined list of all detected emotes (Twitch + Custom)
        all_detected_emotes: List[Dict[str, any]] = [] # Use a dictionary for more flexibility
        processed_emote_names = set() # Keep track of emotes added to avoid duplicates

        # 1. Process standard Twitch emotes from tags
        if message.tags and message.tags.get('emotes'):
            emote_tag = message.tags['emotes']
            try:
                for emote_part in emote_tag.split('/'):
                    emote_id, ranges = emote_part.split(':', 1)
                    first_range = ranges.split(',')[0]
                    start, end = map(int, first_range.split('-'))
                    emote_name = message.content[start:end+1]
                    if emote_name not in processed_emote_names:
                        emote_url = f"https://static-cdn.jtvnw.net/emoticons/v2/{emote_id}/default/dark/1.0"
                        # Use sentiment score if available from analyze_sentiment's word_scores
                        # (prioritizing CSV scores done within analyze_sentiment)
                        emote_sentiment = sentiment_words.get(emote_name)
                        all_detected_emotes.append({
                            "name": emote_name,
                            "url": emote_url,
                            "type": "twitch",
                            "sentiment_score": emote_sentiment # Can be None
                        })
                        processed_emote_names.add(emote_name)
            except Exception as e:
                logger.warning(f"Failed to parse Twitch emote tag '{emote_tag}': {e}")

        # 2. Process custom emotes (FFZ/7TV/BTTV)
        for custom_emote in all_custom_emotes:
            emote_name = custom_emote['name']
            if emote_name not in processed_emote_names:
                 # Use sentiment score if available from analyze_sentiment's word_scores
                 emote_sentiment = sentiment_words.get(emote_name)
                 all_detected_emotes.append({
                    "name": emote_name,
                    "url": custom_emote['url'],
                    "type": custom_emote.get('source', 'custom'), # Track source if available
                    "sentiment_score": emote_sentiment # Can be None
                 })
                 processed_emote_names.add(emote_name)

        # Note: The logic for enhanced_sentiment using analyze_emote_sentiment is removed
        # as analyze_sentiment now incorporates emote scores directly if found in CSV.
        # We will use the compound score returned by the updated analyze_sentiment.

        processed_data = {
            "type": "chat_message",
            "payload": {
                "timestamp": message.timestamp.isoformat(),
                "author": message.author.name,
                "content": message.content,
                "tags": message.tags,
                "sentiment_score": sentiment_score, # Use the compound score from analyze_sentiment
                "sentiment_words": sentiment_words, # <-- ADDED word scores dictionary
                # "original_sentiment_score": sentiment, # Removed, redundant now
                "keywords": keywords,
                "detected_emotes": all_detected_emotes # Includes sentiment if available
            }
        }

        # Send processed data to WebSocket clients for this streamer
        await self.ws_manager.broadcast_to_streamer(self.streamer_channel, processed_data)

    async def event_error(self, error: Exception, data: str | None = None):
        logger.error(f"Twitch Bot Error for {self.streamer_channel}: {error}")
        if isinstance(error, AuthenticationError):
            logger.error("Authentication failed. Please check your TWITCH_ACCESS_TOKEN.")
            await self.ws_manager.broadcast_to_streamer(
                self.streamer_channel,
                {"type": "error", "payload": "Twitch authentication failed. Check backend token."}
            )
            # Potentially stop the bot or signal the main application
        # Log additional data if available
        if data:
            logger.error(f"Error Data: {data}")
        # Propagate error state via WebSocket
        await self.ws_manager.broadcast_to_streamer(
            self.streamer_channel,
            {"type": "error", "payload": f"Twitch IRC error: {str(error)}"}
        )
        # Default twitchio behavior might try to reconnect, depending on the error.
        # We might need custom handling here based on specific errors.

    async def event_close(self):
        logger.warning(f"Twitch IRC connection closed for {self.streamer_channel}.")
        # Cancel emote fetch task if running
        if self._emote_fetch_task and not self._emote_fetch_task.done():
            self._emote_fetch_task.cancel()
            logger.info(f"Cancelled emote fetch task for {self.streamer_channel}")
        await self.ws_manager.broadcast_to_streamer(
            self.streamer_channel,
            {"type": "status", "payload": f"IRC connection closed for {self.streamer_channel}."}
        )
        # Note: twitchio handles reconnection automatically by default for many cases.

    async def stop_bot(self):
        logger.info(f"Stopping Twitch bot for {self.streamer_channel}")
        # Cancel emote fetch task
        if self._emote_fetch_task and not self._emote_fetch_task.done():
            self._emote_fetch_task.cancel()
            logger.info(f"Cancelled emote fetch task during stop for {self.streamer_channel}")
        await self.close()
        logger.info(f"Twitch bot for {self.streamer_channel} closed.")

# --- Manager for Bot Instances --- 
# We need a way to manage multiple bot instances, one per streamer
active_bots: dict[str, TwitchBot] = {}

async def start_twitch_bot(streamer_name: str, ws_manager: ConnectionManager) -> Optional[TwitchBot]:
    """Starts a Twitch bot for the specified streamer if not already running."""
    streamer_name = streamer_name.lower()
    if streamer_name in active_bots:
        logger.warning(f"Bot for {streamer_name} already running.")
        # Optionally notify client it's already running
        await ws_manager.broadcast_to_streamer(streamer_name, {"type": "status", "payload": f"Analysis already running for {streamer_name}."})
        return active_bots[streamer_name]

    # Use anonymous login if no token provided
    irc_token_exists = bool(TWITCH_ACCESS_TOKEN)
    
    if not irc_token_exists:
        logger.warning(f"TWITCH_ACCESS_TOKEN not found for {streamer_name}. Attempting anonymous login.")
        # Notify client about anonymous login
        await ws_manager.broadcast_to_streamer(
            streamer_name,
            {"type": "warning", "payload": "Connecting to Twitch anonymously. Bot functionality might be limited."}
        )

    if not TWITCH_CLIENT_ID:
         logger.warning("TWITCH_CLIENT_ID not set. 7TV emote fetching will likely fail.")

    logger.info(f"Starting Twitch bot for {streamer_name}")
    bot = TwitchBot(streamer_channel=streamer_name, ws_manager=ws_manager)
    active_bots[streamer_name] = bot

    try:
        # Start the bot in a separate task
        # loop = asyncio.get_running_loop()
        # loop.create_task(bot.start())
        asyncio.create_task(bot.start(), name=f"TwitchBotTask-{streamer_name}")
        logger.info(f"Twitch bot task created for {streamer_name}")
        return bot

    except AuthenticationError as e:
        logger.error(f"Authentication error starting bot for {streamer_name}: {e}")
        await ws_manager.broadcast_to_streamer(
            streamer_name,
            {"type": "error", "payload": f"Twitch Auth Error: {e}. Check credentials."}
        )
        if streamer_name in active_bots:
            del active_bots[streamer_name] # Clean up if entry was added before error
        return None
    except Exception as e:
        logger.error(f"Unexpected error starting bot for {streamer_name}: {e}", exc_info=True)
        await ws_manager.broadcast_to_streamer(
            streamer_name,
            {"type": "error", "payload": f"Server error starting analysis: {e}"}
        )
        if streamer_name in active_bots:
            del active_bots[streamer_name] # Clean up
        return None

async def stop_twitch_bot(streamer_name: str):
    """Stops the Twitch bot for the specified streamer."""
    streamer_name = streamer_name.lower()
    bot = active_bots.pop(streamer_name, None)
    if bot:
        logger.info(f"Requesting bot stop for {streamer_name}...")
        try:
            await bot.stop_bot()
            logger.info(f"Bot stop initiated for {streamer_name}.")
            return True
        except Exception as e:
            logger.error(f"Error during bot stop for {streamer_name}: {e}", exc_info=True)
            return False
    else:
        logger.warning(f"No active bot found for {streamer_name} to stop.")
        return False # Indicate bot was not found

def get_active_bot_count():
    """Returns the number of currently active bot instances."""
    return len(active_bots) 