export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
export const WEBSOCKET_URL = import.meta.env.VITE_WEBSOCKET_URL ?? 'ws://localhost:8000/api/ws';

// SYSTEM_PROMPT used to be duplicated here verbatim from the backend. Nothing
// imported it once the model call moved server-side, and keeping a second
// copy meant the two could silently diverge. The live prompt is the only one:
// backend/app/agent_prompt.py::SYSTEM_PROMPT
