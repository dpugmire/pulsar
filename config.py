import os

PULSAR_SQLITE_DB = os.getenv("PULSAR_SQLITE_DB", "")
PULSAR_CACHE_DIR = os.getenv("PULSAR_CACHE_DIR", "~/.cache/pulsar")
PULSAR_INTERACTION_LOG_DIR = os.getenv("PULSAR_INTERACTION_LOG_DIR", "").strip()
PULSAR_INTERACTION_LOG_MAX_MB = int(
    os.getenv("PULSAR_INTERACTION_LOG_MAX_MB", "64")
)

CAMPAIGN_PATH = os.getenv("CAMPAIGN_PATH", "kh.aca")

SOURCE_FIELDS = ["source_dataset", "producer", "casename", "file", "min", "max"]

MOVIE_FPS = int(os.getenv("MOVIE_FPS", "2"))
MAX_MOVIE_FRAMES = int(os.getenv("MAX_MOVIE_FRAMES", "240"))

PULSAR_LLM_MODEL = os.getenv("PULSAR_LLM_MODEL", "").strip()
PULSAR_LLM_API_KEY = os.getenv("PULSAR_LLM_API_KEY", "ollama").strip()
PULSAR_LLM_BASE_URL = os.getenv(
    "PULSAR_LLM_BASE_URL", "http://localhost:11434/v1"
).strip()
PULSAR_LLM_TIMEOUT_SECONDS = float(
    os.getenv("PULSAR_LLM_TIMEOUT_SECONDS", "30")
)
