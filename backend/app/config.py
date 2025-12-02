import os
class Settings:
    PROJECT_NAME: str = "SchedulerAI Backend"
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./simulation.db")
    NUM_SERVERS: int = int(os.getenv("NUM_SERVERS", 8))
    SIM_DELAY: float = float(os.getenv("SIM_DELAY", 0.1))  # Seconds per step
    CORS_ORIGINS: list = ["*"]

settings = Settings()