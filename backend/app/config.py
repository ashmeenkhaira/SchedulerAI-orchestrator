import os
from pathlib import Path

from dotenv import load_dotenv

# backend/.env — loaded explicitly by path so the values are present no matter
# which directory uvicorn or the evaluation scripts were launched from.
# Real environment variables win, which is what Render and CI supply.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)


class Settings:
    PROJECT_NAME: str = "SchedulerAI Backend"
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./simulation.db")

    # Both of these are now actually read: NUM_SERVERS by start_run/_simulate,
    # SIM_DELAY by SimEngine.run_loop. They were previously declared here and
    # ignored, with the cluster size coming from a default argument and the
    # tick from a hardcoded literal.
    NUM_SERVERS: int = int(os.getenv("NUM_SERVERS", 8))
    # Seconds per simulation step. 0.5 gives the 2 steps/second the engine
    # comment always claimed; the observed rate used to be 1.5s/step because
    # ConnectionManager.broadcast slept an extra second inside the loop body.
    SIM_DELAY: float = float(os.getenv("SIM_DELAY", 0.5))

    # Comma-separated list of allowed origins in production, e.g.
    # "https://app.example.com". Falls back to "*" for local development.
    CORS_ORIGINS: list = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "*").split(",")
        if origin.strip()
    ]

    # --- Agent backend ---
    #
    # The evaluation harness issues hundreds of calls per sweep, which is more
    # than Gemini's free per-day quota allows, so Ollama is the default. The
    # decision contract (see agent_service.DECISION_SCHEMA) is identical either
    # way, so which provider produced a decision never changes how it is
    # scored.
    AGENT_PROVIDER: str = os.getenv("AGENT_PROVIDER", "ollama").strip().lower()

    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    OLLAMA_API_KEY: str = os.getenv("OLLAMA_API_KEY", "").strip()
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "gpt-oss:120b-cloud").strip()

    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()


settings = Settings()
