import logging
import nltk
from nltk.corpus import stopwords
# from nltk.tokenize import word_tokenize # No longer using word_tokenize
from nltk.stem import WordNetLemmatizer
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from typing import List, Dict, Tuple, Optional
import os # Import os for path manipulation
import csv # Added for CSV reading

logger = logging.getLogger(__name__)

# --- NLTK Data Download Check & Path Configuration --- 

# Define a local directory for NLTK data within the backend folder
BACKEND_DIR = os.path.dirname(__file__)
NLTK_DATA_DIR = os.path.join(BACKEND_DIR, 'nltk_data')
# Path to the emoji sentiment scores CSV
EMOJI_SENTIMENT_CSV = os.path.join(os.path.dirname(BACKEND_DIR), 'emoji_sentiment_scores.csv')

# --- Load Emoji Sentiment Scores ---
emote_sentiment_scores: Dict[str, float] = {}

def load_emote_sentiment_scores():
    """Loads emote sentiment scores from the CSV file."""
    global emote_sentiment_scores
    try:
        if os.path.exists(EMOJI_SENTIMENT_CSV):
            with open(EMOJI_SENTIMENT_CSV, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    emote_name = row.get('EmoteName')
                    sentiment_score = row.get('SentimentScore')
                    if emote_name and sentiment_score:
                        try:
                            emote_sentiment_scores[emote_name] = float(sentiment_score)
                        except ValueError:
                            logger.warning(f"Invalid sentiment score for emote {emote_name}: {sentiment_score}")
            logger.info(f"Loaded {len(emote_sentiment_scores)} emote sentiment scores from CSV")
        else:
            logger.warning(f"Emote sentiment scores CSV file not found at {EMOJI_SENTIMENT_CSV}")
    except Exception as e:
        logger.error(f"Error loading emote sentiment scores: {e}")

# Load emote sentiment scores when module is loaded
load_emote_sentiment_scores()

def reload_emote_sentiment_scores():
    """Reloads emote sentiment scores from CSV file.
    Can be called to update scores at runtime without restarting application.
    Returns: Number of loaded emotes.
    """
    old_count = len(emote_sentiment_scores)
    # Clear existing scores first
    emote_sentiment_scores.clear()
    # Reload from file
    load_emote_sentiment_scores()
    new_count = len(emote_sentiment_scores)
    logger.info(f"Reloaded emoji sentiment scores: {old_count} -> {new_count} emotes")
    return new_count

# Ensure this directory exists
if not os.path.exists(NLTK_DATA_DIR):
    try:
        os.makedirs(NLTK_DATA_DIR)
        logger.info(f"Created NLTK data directory: {NLTK_DATA_DIR}")
    except OSError as e:
        logger.error(f"Could not create NLTK data directory {NLTK_DATA_DIR}: {e}")
        # Proceed, but download might fail if directory is needed and couldn't be created

# Add the local directory to NLTK's data path *before* trying to download or find
if NLTK_DATA_DIR not in nltk.data.path:
    nltk.data.path.append(NLTK_DATA_DIR)
    logger.info(f"Appended local path to NLTK data search paths: {NLTK_DATA_DIR}")

# Check and download NLTK data if missing
def download_nltk_data():
    required_packages = ['punkt', 'averaged_perceptron_tagger', 'stopwords', 'wordnet', 'omw-1.4']
    download_needed = False
    for package_id in required_packages:
        try:
            # Check if the package can be found using NLTK's find mechanism
            # This now includes our local NLTK_DATA_DIR in the search path
            if package_id == 'punkt': nltk.data.find(f'tokenizers/{package_id}')
            elif package_id == 'averaged_perceptron_tagger': nltk.data.find(f'taggers/averaged_perceptron_tagger') # Fixed path
            elif package_id == 'omw-1.4': nltk.data.find(f'corpora/omw-1.4')
            else: nltk.data.find(f'corpora/{package_id}')
            logger.debug(f"NLTK data package '{package_id}' found.")
        except LookupError:
            logger.warning(f"NLTK data package '{package_id}' not found. Attempting download to {NLTK_DATA_DIR}.")
            download_needed = True

    if download_needed:
        logger.info(f"Attempting to download missing NLTK packages to: {NLTK_DATA_DIR}")
        try:
            # Explicitly specify the download directory
            nltk.download(required_packages, download_dir=NLTK_DATA_DIR, quiet=True, raise_on_error=True)
            logger.info("Finished NLTK data download attempt.")
            # Simple verification flag
            logger.info("NLTK packages should now be available locally.")
            return True
        except Exception as e:
            # Fix the TypeError here by ensuring we join strings
            package_list_str = ' '.join(map(str, required_packages))
            logger.error(f"Failed to download NLTK data to {NLTK_DATA_DIR}: {e}", exc_info=False) # exc_info=False to simplify log
            logger.error("Keyword extraction WILL LIKELY FAIL.")
            logger.error(f"Try manually running: python -m nltk.downloader -d \"{NLTK_DATA_DIR}\" {package_list_str}")
            return False
    else:
        logger.info("All required NLTK data packages found (likely in search paths).")
        return True

# Run the download check when the module is loaded
NLTK_DATA_READY = download_nltk_data()

# --- Initialization (Continues after check/download attempt) --- 

# Initialize VADER sentiment analyzer
vader_analyzer = SentimentIntensityAnalyzer()

# Initialize NLTK components (lemmatizer, stopwords)
lemmatizer = WordNetLemmatizer()
try:
    # This should now hopefully find the data in NLTK_DATA_DIR if downloaded
    stop_words = set(stopwords.words('english'))
except LookupError:
    logger.error("NLTK stopwords lookup failed EVEN AFTER check/download attempt.")
    logger.error("Verify the NLTK_DATA_DIR and permissions.")
    stop_words = set() # Fallback to empty set

# Define relevant POS tags for keywords (Nouns, Proper Nouns)
KEYWORD_POS_TAGS = {'NN', 'NNS', 'NNP', 'NNPS'}

# --- Functions --- 

def analyze_sentiment(text: str) -> Tuple[Optional[float], Dict[str, float]]:
    """Analyzes the sentiment of a text string using VADER and returns word scores.

    Args:
        text: The input text.

    Returns:
        A tuple containing:
        - compound_score: The overall compound sentiment score (-1.0 to 1.0), or None if error.
        - word_scores: A dictionary mapping tokens (words) to their sentiment scores.
                       Emotes from the CSV have precedence.
    """
    if not text:
        return 0.0, {}

    word_scores: Dict[str, float] = {}
    compound_score: Optional[float] = None
    words_in_text = text.split()

    # 1. Check for emotes from our CSV and assign their scores first
    found_csv_emotes = False
    for word in words_in_text:
        # Check original case and lower case for emotes
        if word in emote_sentiment_scores:
            word_scores[word] = emote_sentiment_scores[word]
            found_csv_emotes = True
        elif word.lower() in emote_sentiment_scores:
             word_scores[word] = emote_sentiment_scores[word.lower()]
             found_csv_emotes = True

    # 2. Use VADER for the whole text to get compound score and initial word breakdown
    try:
        vs = vader_analyzer.polarity_scores(text)
        compound_score = round(vs['compound'], 3)

        # 3. Extract VADER scores for non-emote words (Simplified Approach)
        # Get scores for words NOT already scored as emotes
        # This ignores VADER's context handling but gives individual word polarity
        for word in words_in_text:
            if word not in word_scores and word.lower() not in word_scores:
                word_vs = vader_analyzer.polarity_scores(word)
                # We only store non-neutral scores to highlight impactful words
                if word_vs['compound'] != 0.0:
                    word_scores[word] = round(word_vs['compound'], 3)
                    
        # --- Refinement for Emote Blending (Not currently implemented) --- 
        # If we found CSV emotes, we could re-calculate the compound score
        # by blending VADER's score with the CSV emote scores. 
        # For simplicity, we return VADER's compound score for the whole text 
        # and the word_scores dictionary which prioritizes CSV emotes.

    except Exception as e:
        logger.error(f"Error during VADER sentiment analysis for text '{text[:50]}...': {e}")
        # Return None for score and potentially partial word scores on error
        return None, word_scores

    return compound_score, word_scores

def analyze_emote_sentiment(text: str) -> float | None:
    """DEPRECATED (sentiment analysis now integrated). Checks text for emotes and returns score."""
    # Trim whitespace and check if the text is a single emote
    text = text.strip()
    if text in emote_sentiment_scores:
        return emote_sentiment_scores[text]
    
    # No emotes found or single word that's not an emote
    return None

def extract_keywords(text: str, max_keywords: int = 5) -> List[str]:
    """Extracts keywords (nouns) from text using NLTK.

    Args:
        text: The input text.
        max_keywords: The maximum number of keywords to return.

    Returns:
        A list of keywords (lemmatized nouns).
    """
    if not NLTK_DATA_READY:
        logger.warning("NLTK data not ready, skipping keyword extraction.")
        return []

    try:
        # Tokenize using VADER's method for better consistency (handles punctuation, case)
        # Directly using text.split() might be too naive for POS tagging
        # Alternative: Use nltk.word_tokenize if vader method is inaccessible/complex
        # For now, using simple split and lowercasing, acknowledging limitations
        tokens = [word.lower() for word in text.split() if word.isalpha()] # Basic tokenization

        # Remove stopwords
        filtered_tokens = [w for w in tokens if not w in stop_words]

        # Part-of-speech tagging
        tagged_tokens = nltk.pos_tag(filtered_tokens)

        # Lemmatize and filter for relevant POS tags
        keywords = [
            lemmatizer.lemmatize(word)
            for word, tag in tagged_tokens
            if tag in KEYWORD_POS_TAGS
        ]

        # Get frequency distribution
        freq_dist = nltk.FreqDist(keywords)

        # Return the most common keywords
        return [kw for kw, _ in freq_dist.most_common(max_keywords)]

    except Exception as e:
        logger.error(f"Error extracting keywords from text '{text[:50]}...': {e}", exc_info=False)
        return []

# --- Example Usage --- 
if __name__ == "__main__":
    # The download check now runs automatically when the script starts

    test_texts = [
        "This game is amazing and fun! Really enjoying the stream. LUL",
        "Man, that play was terrible. So bad.",
        "He is playing League of Legends now.",
        "Good start, but that ending was awful.",
        "OMEGALUL that was hilarious",
        "I hate this matchup so much :( ",
        "Just chatting today?"
    ]

    print("--- Testing NLP Processor (VADER + NLTK) ---")
    if NLTK_DATA_READY:
        print(f"NLTK data should be ready in {NLTK_DATA_DIR} (or other standard paths).")
        for text in test_texts:
            sentiment, word_scores = analyze_sentiment(text)
            keywords = extract_keywords(text)
            print(f"Text:      {text}")
            print(f"Sentiment: {sentiment}")
            print(f"Word Scores: {word_scores}")
            print(f"Keywords:  {keywords}")
            print("---")
    else:
        print(f"\nNLTK data download/check failed. Cannot run keyword extraction examples.")
        print(f"Sentiment analysis (VADER) should still work:")
        for text in test_texts:
             sentiment, word_scores = analyze_sentiment(text)
             print(f"Text:      {text}")
             print(f"Sentiment: {sentiment}")
             print(f"Word Scores: {word_scores}")
             print("---") 