import logging
import httpx
import asyncio
from typing import Set, Dict, Optional, Tuple, List, TypedDict

logger = logging.getLogger(__name__)

# --- Type Definitions ---
class EmoteData(TypedDict):
    name: str
    url: str # Typically the smallest size URL (1x)
    sentiment_score: Optional[float]  # Added sentiment score field
    # Optionally add source: Literal['ffz', '7tv', 'twitch']

# Store emote data as {name: url} dictionaries for easier lookup
EmoteSet = Dict[str, str] 

# --- Custom Emote Sentiment Scores ---
# This is populated by nlp_processor.py, we declare it here for reference
# The actual data is loaded in nlp_processor and imported here
try:
    from nlp_processor import emote_sentiment_scores
    logger.info(f"Imported {len(emote_sentiment_scores)} emote sentiment scores from nlp_processor")
except ImportError:
    logger.error("Failed to import emote_sentiment_scores from nlp_processor")
    emote_sentiment_scores = {}

# --- API Endpoints --- (These might change, verify if needed)
FFZ_ROOM_API = "https://api.frankerfacez.com/v1/room/{channel_name}"
SEVENTV_USER_API = "https://7tv.io/v3/users/twitch/{channel_id}" # Requires Twitch User ID
SEVENTV_GLOBAL_API = "https://7tv.io/v3/emote-sets/global"

# --- Twitch API Helper (Placeholder) --- 
# We need the Twitch User ID for the 7TV API. This requires a Twitch API call.
# We'll use a placeholder function for now. Needs proper implementation later.
# Requires adding 'twitchAPI' library or similar and handling authentication.
TWITCH_API_USERS = "https://api.twitch.tv/helix/users"
async def get_twitch_user_id(channel_name: str, client_id: Optional[str], token: Optional[str]) -> Optional[str]:
    # Uses httpx to call Twitch API. Requires client_id and token.
    if not client_id or not token:
        logger.error("Twitch Client ID or Token missing for User ID lookup.")
        return None
    headers = {
        "Client-ID": client_id,
        "Authorization": f"Bearer {token.replace('oauth:', '')}"
    }
    params = {"login": channel_name.lower()}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(TWITCH_API_USERS, headers=headers, params=params)
            response.raise_for_status() # Raise exception for bad status codes
            data = response.json()
            if data.get("data") and len(data["data"]) > 0:
                user_id = data["data"][0]["id"]
                logger.info(f"Got Twitch User ID for {channel_name}: {user_id}")
                return user_id
            else:
                logger.warning(f"Could not find Twitch User ID for channel: {channel_name}")
                return None
    except httpx.RequestError as e:
        logger.error(f"HTTP error getting Twitch User ID for {channel_name}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error getting Twitch User ID for {channel_name}: {e}", exc_info=True)
        return None

# --- Emote Fetching Functions --- 

async def get_ffz_emotes(channel_name: str) -> EmoteSet:
    """Fetches FrankerFaceZ channel emotes.
    Returns: A dictionary mapping emote name to its 1x URL.
    """
    emotes: EmoteSet = {}
    url = FFZ_ROOM_API.format(channel_name=channel_name.lower())
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            if response.status_code == 404:
                logger.info(f"No FFZ room data found for channel: {channel_name}")
                return emotes # Channel might not use FFZ
            response.raise_for_status()
            data = response.json()

            # FFZ data structure: room -> sets -> set_id -> emotes
            if "sets" in data:
                for set_id, emote_set in data["sets"].items():
                    if "emoticons" in emote_set:
                        for emote in emote_set["emoticons"]:
                            # Get the smallest URL (usually "1")
                            emote_url = emote.get('urls', {}).get('1')
                            if emote_url:
                                # FFZ URLs might not include protocol, add https:
                                emotes[emote["name"]] = emote_url if emote_url.startswith('http') else f"https:{emote_url}"
            logger.info(f"Fetched {len(emotes)} FFZ emotes for channel: {channel_name}")
            return emotes
    except httpx.RequestError as e:
        logger.error(f"HTTP error fetching FFZ emotes for {channel_name}: {e}")
    except Exception as e:
        logger.error(f"Error processing FFZ data for {channel_name}: {e}", exc_info=True)
    return emotes # Return empty set on error

async def get_7tv_emotes(channel_id: str) -> EmoteSet:
    """Fetches 7TV channel emotes using Twitch User ID.
    Returns: A dictionary mapping emote name to its 1x WebP URL.
    """
    emotes: EmoteSet = {}
    if not channel_id:
        return emotes

    url = SEVENTV_USER_API.format(channel_id=channel_id)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            if response.status_code == 404:
                 logger.info(f"No 7TV user data found for channel ID: {channel_id}")
                 return emotes # Channel might not use 7TV
            response.raise_for_status()
            data = response.json()

            # 7TV data structure can vary, often has an emote_set -> emotes list
            emote_list = []
            emote_set = data.get("emote_set")
            if emote_set and "emotes" in emote_set:
                emote_list = emote_set["emotes"]
            elif "emotes" in data: # Sometimes emotes might be directly in the user data
                 emote_list = data["emotes"]
            
            for emote in emote_list:
                emote_name = emote.get("name")
                # Get the smallest WebP URL (1x)
                emote_url = None
                files = emote.get("data", {}).get("host", {}).get("files", [])
                for f in files:
                    if f.get("name") == "1x.webp":
                        emote_url = f"{emote['data']['host']['url']}/{f['name']}"
                        break 
                if emote_name and emote_url:
                    emotes[emote_name] = emote_url

            logger.info(f"Fetched {len(emotes)} 7TV emotes for channel ID: {channel_id}")
            return emotes
    except httpx.RequestError as e:
        logger.error(f"HTTP error fetching 7TV emotes for {channel_id}: {e}")
    except Exception as e:
        logger.error(f"Error processing 7TV data for {channel_id}: {e}", exc_info=True)
    return emotes

async def get_7tv_global_emotes() -> EmoteSet:
    """Fetches 7TV global emotes.
    Returns: A dictionary mapping emote name to its 1x WebP URL.
    """
    emotes: EmoteSet = {}
    url = SEVENTV_GLOBAL_API
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            if "emotes" in data:
                for emote in data["emotes"]:
                    emote_name = emote.get("name")
                    # Get the smallest WebP URL (1x)
                    emote_url = None
                    files = emote.get("data", {}).get("host", {}).get("files", [])
                    for f in files:
                        if f.get("name") == "1x.webp":
                            emote_url = f"{emote['data']['host']['url']}/{f['name']}"
                            break 
                    if emote_name and emote_url:
                        emotes[emote_name] = emote_url
            logger.info(f"Fetched {len(emotes)} 7TV global emotes.")
            return emotes
    except httpx.RequestError as e:
        logger.error(f"HTTP error fetching 7TV global emotes: {e}")
    except Exception as e:
        logger.error(f"Error processing 7TV global data: {e}", exc_info=True)
    return emotes

# --- Main Fetch Function & Cache --- 

# Cache maps channel name to tuple: (ffz_dict, 7tv_chan_dict)
emote_cache: Dict[str, Tuple[EmoteSet, EmoteSet]] = {}
# Cache for 7TV global emotes
seventv_global_cache: Optional[EmoteSet] = None
CACHE_EXPIRY = 3600 # Cache emotes for 1 hour (in seconds) - adjust as needed

async def fetch_all_emotes_for_channel(channel_name: str, client_id: Optional[str], token: Optional[str]) -> Tuple[EmoteSet, EmoteSet, EmoteSet]:
    """Fetches FFZ, 7TV channel, and 7TV global emotes for a channel.
    Returns: A tuple containing: (ffz_emotes_dict, seventv_channel_emotes_dict, seventv_global_emotes_dict)
    """
    global seventv_global_cache
    channel_name_lower = channel_name.lower()

    # --- Fetch 7TV Global Emotes (if not cached) --- 
    if seventv_global_cache is None:
        logger.info("Fetching 7TV global emotes...")
        seventv_global_cache = await get_7tv_global_emotes()

    # --- Fetch Channel Specific Emotes --- 
    # Get Twitch User ID first (needed for 7TV)
    twitch_user_id = await get_twitch_user_id(channel_name_lower, client_id, token)

    # Fetch FFZ and 7TV concurrently
    results = await asyncio.gather(
        get_ffz_emotes(channel_name_lower),
        get_7tv_emotes(twitch_user_id) if twitch_user_id else asyncio.sleep(0, result={}), # Return empty dict if no ID
        return_exceptions=True # Don't let one failure stop others
    )

    ffz_emotes = results[0] if not isinstance(results[0], Exception) else {}
    seventv_channel_emotes = results[1] if not isinstance(results[1], Exception) else {}

    if isinstance(results[0], Exception):
        logger.error(f"Exception fetching FFZ for {channel_name_lower}: {results[0]}")
    if isinstance(results[1], Exception):
        logger.error(f"Exception fetching 7TV for {channel_name_lower} (ID: {twitch_user_id}): {results[1]}")

    # --- Update Cache --- 
    emote_cache[channel_name_lower] = (ffz_emotes, seventv_channel_emotes)
    # logger.info(f"Cached emotes for {channel_name_lower}: FFZ({len(ffz_emotes)}), 7TV({len(seventv_channel_emotes)})")

    return ffz_emotes, seventv_channel_emotes, seventv_global_cache or {}


# --- Emote Detection --- 

def detect_emotes_in_message(message_content: str, ffz_emotes: EmoteSet, seventv_emotes: EmoteSet, global_seventv_emotes: EmoteSet) -> List[EmoteData]:
    """Detects known FFZ and 7TV emotes in a message string.
    Returns: A list of detected emote data (name, URL, and sentiment score if available).
    Prioritizes emotes from emoji_sentiment_scores.csv.
    """
    detected: List[EmoteData] = []
    words = message_content.split()
    
    # Combine emote dictionaries for efficient lookup
    # Channel-specific emotes override global ones if names clash
    combined_emotes: EmoteSet = {**global_seventv_emotes, **ffz_emotes, **seventv_emotes} 

    for word in words:
        if word in combined_emotes:
            # Check if this emote is in our sentiment scores dataset
            has_sentiment = word in emote_sentiment_scores
            
            emote_data: EmoteData = {
                "name": word, 
                "url": combined_emotes[word],
                "sentiment_score": None  # Default to None
            }
            
            # Add sentiment score if available in our custom dataset
            if has_sentiment:
                emote_data["sentiment_score"] = emote_sentiment_scores[word]
                detected.append(emote_data)
            # If we want to strictly only use emotes from emoji_sentiment_scores.csv, we can
            # remove this else block. If we want to include all but prioritize, keep it.
            # else:
            #    detected.append(emote_data)

    return detected 