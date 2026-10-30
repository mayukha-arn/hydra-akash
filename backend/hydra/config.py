from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Read KEY=value lines from .env without overriding the real environment."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


@dataclass
class Config:
    mode: str = "simulate"  # "simulate" or "live"
    replicas: int = 3
    strikes: int = 3
    probe_interval: float = 2.0
    boot_grace: float = 0.0  # seconds a new replica gets before probes count
    bid_timeout: float = 90.0
    bid_poll: float = 5.0
    database_path: str = ":memory:"
    sdl_path: str = str(ROOT / "sdl" / "web.yaml")
    domain: str = "app.example.com"
    akash_api_key: str = ""
    cloudflare_api_token: str = ""
    cloudflare_zone_id: str = ""

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        env = os.environ
        mode = env.get("HYDRA_MODE", "simulate")
        live = mode == "live"
        url = env.get("DATABASE_URL", "sqlite:///hydra.db")
        return cls(
            mode=mode,
            replicas=int(env.get("HYDRA_REPLICAS", "3")),
            strikes=int(env.get("HYDRA_STRIKES", "3")),
            probe_interval=float(env.get("HYDRA_PROBE_INTERVAL", "15" if live else "2")),
            boot_grace=float(env.get("HYDRA_BOOT_GRACE", "120" if live else "0")),
            database_path=url.replace("sqlite:///", "", 1) if live else ":memory:",
            domain=env.get("HYDRA_DOMAIN", "app.example.com"),
            akash_api_key=env.get("AKASH_API_KEY", ""),
            cloudflare_api_token=env.get("CLOUDFLARE_API_TOKEN", ""),
            cloudflare_zone_id=env.get("CLOUDFLARE_ZONE_ID", ""),
        )
