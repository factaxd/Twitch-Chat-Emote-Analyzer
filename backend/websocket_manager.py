from fastapi import WebSocket
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # Dictionary to hold active connections per streamer
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, streamer_name: str):
        await websocket.accept()
        streamer_name = streamer_name.lower()
        if streamer_name not in self.active_connections:
            self.active_connections[streamer_name] = []
        self.active_connections[streamer_name].append(websocket)
        logger.info(f"WebSocket connected for {streamer_name}. Total clients: {len(self.active_connections[streamer_name])}")

    async def disconnect(self, websocket: WebSocket, streamer_name: str):
        streamer_name = streamer_name.lower()
        if streamer_name in self.active_connections:
            try:
                self.active_connections[streamer_name].remove(websocket)
                # Clean up streamer entry if no clients are left
                if not self.active_connections[streamer_name]:
                    del self.active_connections[streamer_name]
                    logger.info(f"Last client disconnected for {streamer_name}. Removing entry.")
                else:
                    logger.info(f"WebSocket disconnected for {streamer_name}. Remaining clients: {len(self.active_connections[streamer_name])}")
            except ValueError:
                logger.warning(f"Attempted to remove a non-existent WebSocket for {streamer_name}")
                pass # Connection already removed
            except Exception as e:
                logger.error(f"Error during WebSocket disconnect for {streamer_name}: {e}")

    async def broadcast_to_streamer(self, streamer_name: str, message: dict):
        streamer_name = streamer_name.lower()
        if streamer_name in self.active_connections:
            disconnected_clients = []
            # Iterate over a copy in case disconnect modifies the list during iteration
            for connection in self.active_connections[streamer_name][:]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    # Log error and mark client for removal
                    logger.warning(f"Failed to send message to client for {streamer_name}: {e}. Marking for disconnect.")
                    disconnected_clients.append(connection)

            # Remove disconnected clients
            for client in disconnected_clients:
                await self.disconnect(client, streamer_name)

    async def broadcast_all(self, message: dict):
        # Send message to all clients across all streamers
        all_connections = [conn for conns in self.active_connections.values() for conn in conns]
        disconnected_clients = []
        streamer_map = {conn: streamer for streamer, conns in self.active_connections.items() for conn in conns}

        for connection in all_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                 logger.warning(f"Failed to broadcast message: {e}. Marking for disconnect.")
                 disconnected_clients.append(connection)

        for client in disconnected_clients:
            streamer = streamer_map.get(client)
            if streamer:
                await self.disconnect(client, streamer)