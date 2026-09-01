import os
class Settings:
    PROJECT_NAME: str = "SchedulerAI Backend"
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./simulation.db")
    NUM_SERVERS: int = int(os.getenv("NUM_SERVERS", 8))
    SIM_DELAY: float = float(os.getenv("SIM_DELAY", 0.1))  # Seconds per step
    # Comma-separated list of allowed origins in production, e.g.
    # "https://app.example.com,https://www.example.com". Falls back to "*"
    # for local development only.
    CORS_ORIGINS: list = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "*").split(",")
        if origin.strip()
    ]
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

settings = Settings()