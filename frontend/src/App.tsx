import React, { useState, useRef, useEffect, useCallback } from 'react';
// Import Recharts components
import {
    LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar
} from 'recharts';
import './App.css';


// --- Type Definitions --- 
interface EmoteData {
    name: string;
    url: string;
    type?: string; // Optional: twitch, ffz, 7tv etc.
    sentiment_score?: number | null; // Optional: sentiment score for the emote itself
}

interface ChatMessagePayload {
  timestamp: string;
  author: string;
  content: string;
  tags: Record<string, any>; // Twitch IRC tags
  sentiment_score: number | null;
  sentiment_words: Record<string, number>; // <-- ADDED word scores { word: score }
  keywords: string[];
  detected_emotes: EmoteData[];
}

// Add a unique ID to messages for list keys
interface DisplayMessage extends ChatMessagePayload {
    id: string; 
}

// Type for sentiment chart data points
interface SentimentDataPoint {
    time: number; // Use a numeric value for charting (e.g., message index or timestamp)
    score: number;
}

// Union type for different WebSocket message types
type WebSocketMessage = 
  | { type: 'chat_message', payload: ChatMessagePayload }
  | { type: 'status', payload: string }
  | { type: 'error', payload: string }
  | { type: 'connection_ack', streamer: string }; 

// --- Rendering Helpers --- 

// New component to handle rendering text with sentiment highlighting
interface HighlightedTextProps {
    text: string;
    sentimentWords: Record<string, number>;
}

const HighlightedText: React.FC<HighlightedTextProps> = ({ text, sentimentWords }) => {
    // Split text by space, keeping delimiters (space) for reconstruction
    const parts = text.split(/(\s+)/);

    return (
        <>
            {parts.map((part, index) => {
                // Check if the part (word) exists in sentimentWords (case-insensitive check might be better)
                // We check the original part and a cleaned version (lowercase, no punctuation)
                const lowerPart = part.toLowerCase().replace(/[.,!?;:]$/, ''); // Basic cleaning
                const score = sentimentWords[part] ?? sentimentWords[lowerPart];
                
                if (score !== undefined && score !== 0) { // Highlight non-neutral words
                    let className = 'sentiment-neutral'; // Default (though we skip score 0)
                    if (score > 0.1) className = 'sentiment-positive'; // Threshold for positive
                    else if (score < -0.1) className = 'sentiment-negative'; // Threshold for negative
                    
                    // Use a span to apply the class
                    return <span key={index} className={className}>{part}</span>;
                } else if (part.match(/^\s+$/)) {
                    // If it's just whitespace, render it directly
                    return <React.Fragment key={index}>{part}</React.Fragment>;
                } else {
                    // Otherwise, render the part as plain text
                    return <React.Fragment key={index}>{part}</React.Fragment>;
                }
            })}
        </>
    );
};

// Modified emote parsing to integrate HighlightedText
const parseMessageContent = (
    content: string, 
    detectedEmotes: EmoteData[], 
    twitchEmotesTag: string | null | undefined,
    sentimentWords: Record<string, number> // <-- ADDED sentiment words
): React.ReactNode[] => {
    const parts: React.ReactNode[] = [];
    let currentPos = 0;

    // Combine Twitch and custom emotes (ensure EmoteData includes necessary fields)
    const allEmotes: {name: string, url: string, start: number, end: number}[] = [];

    // 1. Parse standard Twitch emotes from tags
    if (twitchEmotesTag) {
         try {
            twitchEmotesTag.split('/').forEach(emotePart => {
                const [emoteId, ranges] = emotePart.split(':'); // Split only once
                if (!ranges || !emoteId) return;
                const url = `https://static-cdn.jtvnw.net/emoticons/v2/${emoteId}/default/dark/1.0`;
                ranges.split(',').forEach(range => {
                    const [startStr, endStr] = range.split('-');
                    const start = parseInt(startStr, 10);
                    const end = parseInt(endStr, 10);
                    if (!isNaN(start) && !isNaN(end) && start <= end) { // Allow single character emotes
                         const name = content.substring(start, end + 1);
                         allEmotes.push({ name, url, start, end });
                    }
                });
            });
        } catch (e) {
            console.error("Failed to parse Twitch emotes tag:", twitchEmotesTag, e);
        }
    }

    // 2. Add detected FFZ/7TV emotes (using the provided detected_emotes list)
    // Find positions for detected custom emotes
    detectedEmotes.forEach(emote => {
        if (!allEmotes.some(e => e.name === emote.name)) { // Avoid duplicates if name matches Twitch emote
            const regex = new RegExp(`\b${escapeRegex(emote.name)}\b`, 'g');
            let match;
            while ((match = regex.exec(content)) !== null) {
                const start = match.index;
                const end = start + emote.name.length - 1;
                 // Basic overlap check (can be improved)
                if (!allEmotes.some(e => Math.max(start, e.start) <= Math.min(end, e.end))) {
                    allEmotes.push({ name: emote.name, url: emote.url, start, end });
                }
            }
        }
    });

    // 3. Sort emotes by start position
    allEmotes.sort((a, b) => a.start - b.start);

    // 4. Build the output array: intersperse highlighted text and images
    for (const emote of allEmotes) {
        // Add text segment before the emote, applying highlighting
        if (emote.start > currentPos) {
            const textSegment = content.substring(currentPos, emote.start);
            parts.push(
                <HighlightedText 
                    key={`text-${currentPos}`} 
                    text={textSegment} 
                    sentimentWords={sentimentWords} 
                />
            );
        }
        // Add the emote image
        parts.push(
            <img 
                key={`${emote.start}-${emote.name}`}
                src={emote.url} 
                alt={emote.name} 
                className="chat-emote-image" 
                // Optionally add title for hover 
                title={emote.name}
            />
        );
        currentPos = emote.end + 1;
    }

    // Add any remaining text after the last emote, applying highlighting
    if (currentPos < content.length) {
        const textSegment = content.substring(currentPos);
         parts.push(
            <HighlightedText 
                key={`text-${currentPos}`} 
                text={textSegment} 
                sentimentWords={sentimentWords} 
            />
        );
    }

    // If the process resulted in no parts (e.g., empty content), return empty array or placeholder
    return parts;
};

// Helper function to escape regex special characters
const escapeRegex = (string: string) => {
  return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); // $& means the whole matched string
}

function App() {
  const [streamerName, setStreamerName] = useState<string>('');
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [isConnecting, setIsConnecting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [currentStreamer, setCurrentStreamer] = useState<string | null>(null);

  // Analytics & Display State
  const [latestMessages, setLatestMessages] = useState<DisplayMessage[]>([]);
  const [keywordCounts, setKeywordCounts] = useState<Record<string, number>>({});
  const [sentimentChartData, setSentimentChartData] = useState<SentimentDataPoint[]>([]);
  const [statusMessage, setStatusMessage] = useState<string>("Enter streamer name to begin.");
  const [averageSentiment, setAverageSentiment] = useState<number | null>(null);
  const [emoteCounts, setEmoteCounts] = useState<Record<string, number>>({}); // <-- Add state for emote counts

  const ws = useRef<WebSocket | null>(null);
  const messageCounter = useRef<number>(0); // Counter for chart X-axis
  const chatLogRef = useRef<HTMLDivElement>(null); // Ref for auto-scrolling chat

  // Constants
  const MAX_MESSAGES_DISPLAY = 100; // Show last 100 messages in chat feed
  const MAX_SENTIMENT_POINTS = 50; // Keep last 50 points for sentiment chart

  // Effect to calculate average sentiment whenever chart data changes
  useEffect(() => {
      // Filter out scores of 0 *and* potentially null if they somehow got in
      const validSentimentData = sentimentChartData.filter(point => point.score !== 0 && point.score !== null);
  
      if (validSentimentData.length > 0) {
          const sum = validSentimentData.reduce((acc, point) => acc + point.score, 0);
          setAverageSentiment(sum / validSentimentData.length);
      } else {
          // If no valid (non-zero, non-null) scores exist in the window, set average to null
          setAverageSentiment(null);
      }
  }, [sentimentChartData]); // Re-run whenever sentimentChartData updates

  const connectWebSocket = useCallback((name: string) => {
    if (!name) {
      setError('Please enter a streamer name.');
      return;
    }
    const streamer = name.trim().toLowerCase();
    setError(null);
    setIsConnecting(true);
    setCurrentStreamer(streamer);
    // Reset state
    setLatestMessages([]);
    setKeywordCounts({});
    setEmoteCounts({}); // <-- Reset emote counts
    setSentimentChartData([]);
    setAverageSentiment(null);
    messageCounter.current = 0;
    setStatusMessage(`Attempting to connect to ${streamer}...`);

    if (ws.current && ws.current.readyState === WebSocket.OPEN) ws.current.close();

    const wsUrl = `ws://localhost:8000/ws/${streamer}`;
    ws.current = new WebSocket(wsUrl);

    ws.current.onopen = () => {
      setIsConnected(true);
      setIsConnecting(false);
      setError(null);
      setStatusMessage('Connection established. Waiting for backend...');
    };

    ws.current.onclose = (event) => {
      setIsConnected(false);
      setIsConnecting(false);
      const reason = `Connection closed. Code: ${event.code}. ${event.reason || 'Unknown'}`;
      setStatusMessage(reason);
      if (!event.wasClean) setError(reason);
    };

    ws.current.onerror = (event) => {
      console.error('WebSocket Error:', event);
      setIsConnected(false);
      setIsConnecting(false);
      const errorMsg = 'WebSocket error. Is the backend running?';
      setError(errorMsg);
      setStatusMessage(errorMsg);
      setCurrentStreamer(null);
    };

    ws.current.onmessage = (event) => {
      try {
        const message: WebSocketMessage = JSON.parse(event.data);

        switch (message.type) {
          case 'connection_ack':
            setStatusMessage(`Backend connected for ${message.streamer}. Waiting for IRC join...`);
            break;
          case 'status':
            setStatusMessage(`Status: ${message.payload}`);
            break;
          case 'error':
            setStatusMessage(`Backend Error: ${message.payload}`);
            setError(`Backend Error: ${message.payload}`); // Show critical errors
            break;
          case 'chat_message':
            const payload = message.payload;
            messageCounter.current += 1;
            
            // Assign ID, using Twitch message ID if available
            const displayMsg: DisplayMessage = { 
                ...payload, 
                id: payload.tags?.id || `${payload.timestamp}-${payload.author}`,
                 // Ensure sentiment_words exists, even if empty (for type safety)
                sentiment_words: payload.sentiment_words || {} 
            };
            
            // Update messages for chat display
            setLatestMessages(prev => {
                const updatedMessages = [...prev, displayMsg];
                // Keep only the last MAX_MESSAGES_DISPLAY messages
                if (updatedMessages.length > MAX_MESSAGES_DISPLAY) {
                    return updatedMessages.slice(updatedMessages.length - MAX_MESSAGES_DISPLAY);
                }
                return updatedMessages;
            });

            // Update sentiment chart data (average calculation moved to useEffect)
            if (payload.sentiment_score !== null) {
                const newDataPoint: SentimentDataPoint = {
                    time: messageCounter.current,
                    score: payload.sentiment_score
                };
                setSentimentChartData(prev => 
                    [...prev.slice(-MAX_SENTIMENT_POINTS + 1), newDataPoint]
                );
            } 
            // No need to handle average calculation here anymore
            
            // Update keyword counts
            if (payload.keywords && payload.keywords.length > 0) {
                setKeywordCounts(prevCounts => {
                    const newCounts = { ...prevCounts };
                    payload.keywords.forEach((kw: string) => {
                        newCounts[kw] = (newCounts[kw] || 0) + 1;
                    });
                    return newCounts;
                });
            }

            // Update emote counts
            if (payload.detected_emotes && payload.detected_emotes.length > 0) {
                setEmoteCounts(prevCounts => {
                    const newCounts = { ...prevCounts };
                    payload.detected_emotes.forEach((emote: EmoteData) => {
                        newCounts[emote.name] = (newCounts[emote.name] || 0) + 1;
                    });
                    // Return unsorted/unlimited counts, handle in getTopEmotesData
                    return newCounts;
                });
            }
            break;
          default:
             console.warn('Received unknown message type:', message);
             setStatusMessage('Received unknown message from backend.');
        }
      } catch (e) {
        console.error('Failed to parse message or invalid message format:', event.data, e);
        setStatusMessage('Received unparseable message from backend.');
      }
    };
  }, []);

  // Auto-scrolling Effect
  useEffect(() => {
      // Scroll to bottom when new messages arrive
      if (chatLogRef.current) {
          chatLogRef.current.scrollTop = chatLogRef.current.scrollHeight;
      }
  }, [latestMessages]); // Triggered when latestMessages updates

  // Cleanup WebSocket connection on component unmount
  useEffect(() => {
    return () => { if (ws.current) ws.current.close(); };
  }, []);

  const handleStartAnalysis = () => connectWebSocket(streamerName);
  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>) => setStreamerName(event.target.value);
  const handleStopAnalysis = () => {
      if (ws.current) ws.current.close(1000, "User stopped analysis");
      setIsConnected(false);
      setIsConnecting(false);
      setCurrentStreamer(null);
      setStreamerName('');
      setError(null);
      setStatusMessage("Analysis stopped by user.");
      // Optionally clear analytics state on stop?
  };

  // Data Preparation for Charts
  const getTopKeywordsData = (count: number): { name: string, count: number }[] => {
      return Object.entries(keywordCounts)
          .sort(([, countA], [, countB]) => countB - countA)
          .slice(0, count)
          .map(([name, count]) => ({ name, count })); // Format for Recharts BarChart
  };

  // New function for emote chart data
  const getTopEmotesData = (count: number): { name: string, count: number }[] => {
    return Object.entries(emoteCounts) // Already potentially limited/sorted in state update
        .sort(([, countA], [, countB]) => countB - countA) // Sort again to be sure
        .slice(0, count)
        .map(([name, count]) => ({ name, count }));
  };

  // Format average sentiment for display
  const formattedAvgSentiment = averageSentiment !== null
      ? averageSentiment.toFixed(2)
      : 'N/A';

  return (
    <div className="App">
      <header className="app-header">
        <h1>Twitch Chat Real-Time Analyzer</h1>
        <div className="controls">
          <input
            type="text"
            value={streamerName}
            onChange={handleInputChange}
            placeholder="Enter Twitch Streamer Name"
            disabled={isConnecting || isConnected}
          />
          {!isConnected && !isConnecting && (
              <button onClick={handleStartAnalysis} disabled={!streamerName || isConnecting}>
              {isConnecting ? 'Connecting...' : 'Start Analysis'}
              </button>
          )}
          {(isConnected || isConnecting) && (
              <button onClick={handleStopAnalysis} disabled={isConnecting}>
                  {isConnecting ? 'Connecting...' : 'Stop Analysis'}
              </button>
          )}
        </div>
        <div className="status-bar">
            {error && <span className="error">Error: {error}</span>}
            {!error && <span className="status">{statusMessage}</span>}
        </div>
      </header>

      <main className="main-content">
        {/* Chat Feed Area */}  
        <section className="chat-feed-section">
          <h2>Live Chat Feed {currentStreamer ? `for ${currentStreamer}` : ''}</h2>
          <div className="chat-log" ref={chatLogRef}>
            {latestMessages.length === 0 && isConnected && (
                <p className="chat-message system-message">Waiting for messages...</p>
            )}
            {latestMessages.map((msg) => (
              <div key={msg.id} className="chat-message">
                <span className="timestamp">{new Date(msg.timestamp).toLocaleTimeString()}</span>
                <span className="author" style={{ color: msg.tags?.color || '#ffffff' }}>
                  {msg.tags?.['display-name'] || msg.author}:
                </span>
                <span className="content">
                   {/* Use the updated parseMessageContent */}
                   {parseMessageContent(
                       msg.content, 
                       msg.detected_emotes, 
                       msg.tags?.emotes,
                       msg.sentiment_words // <-- Pass sentiment words here
                   )}
                </span>
              </div>
            ))}
          </div>
        </section>

        {/* Dashboard Area */}  
        <section className="dashboard-section">
           <div className="dashboard-header">
             <h2>Analytics Dashboard</h2>
             <span className="average-sentiment">
               Avg Sentiment: {formattedAvgSentiment}
             </span>
           </div>
          {isConnected ? (
            <div className="charts-container">
              {/* Sentiment Chart */}  
              <div className="chart-wrapper">
                <h3>Sentiment Over Time</h3>
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={sentimentChartData} margin={{ top: 5, right: 20, left: -20, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#555" />
                    <XAxis dataKey="time" tick={{ fontSize: 10 }} />
                    <YAxis domain={[-1, 1]} tick={{ fontSize: 10 }} />
                    <Tooltip 
                      contentStyle={{ backgroundColor: '#333', border: 'none'}} 
                      labelStyle={{ color: '#eee' }} 
                      itemStyle={{ color: '#eee' }}
                    />
                    <Line type="monotone" dataKey="score" stroke="#8884d8" dot={false} isAnimationActive={false} name="Sentiment"/>
                  </LineChart>
                </ResponsiveContainer>
              </div>

              {/* Row for Keywords and Emotes charts */}
              <div className="chart-row">
                {/* Keyword Chart */}  
                <div className="chart-wrapper">
                  <h3>Top Keywords</h3>
                  <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={getTopKeywordsData(7)} layout="vertical" margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#555" />
                          <XAxis type="number" tick={{ fontSize: 10 }}/>
                          <YAxis type="category" dataKey="name" width={80} tick={{ fontSize: 10 }}/>
                          <Tooltip 
                              contentStyle={{ backgroundColor: '#333', border: 'none'}} 
                              labelStyle={{ color: '#eee' }} 
                              itemStyle={{ color: '#82ca9d' }}
                            />
                          <Bar dataKey="count" fill="#82ca9d" isAnimationActive={false} name="Frequency"/>
                      </BarChart>
                  </ResponsiveContainer>
                </div>

                {/* Emote Chart */}
                <div className="chart-wrapper">
                  <h3>Top Emotes</h3>
                  <ResponsiveContainer width="100%" height={200}>
                      <BarChart data={getTopEmotesData(7)} layout="vertical" margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#555" />
                          <XAxis type="number" tick={{ fontSize: 10 }}/>
                          <YAxis type="category" dataKey="name" width={80} tick={{ fontSize: 10 }}/>
                          <Tooltip 
                              contentStyle={{ backgroundColor: '#333', border: 'none'}} 
                              labelStyle={{ color: '#eee' }} 
                              itemStyle={{ color: '#ffc658' }}
                            />
                          <Bar dataKey="count" fill="#ffc658" isAnimationActive={false} name="Frequency"/>
                      </BarChart>
                  </ResponsiveContainer>
                </div>
              </div> {/* End of chart-row */}
            </div>
          ) : (
            <p>Start analysis to view dashboard.</p>
          )}
        </section>
      </main>
    </div>
  );
}

export default App;
