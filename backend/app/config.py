import os


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
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")


settings = Settings()
