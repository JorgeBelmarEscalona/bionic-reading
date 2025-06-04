import json
from pathlib import Path
from dataclasses import dataclass, asdict

CONFIG_PATH = Path('settings.json')

@dataclass
class Settings:
    theme: str = 'System'
    dest_folder: str = ''
    dest_subfolder: str = 'Generados'
    language: str = 'en'
    open_on_finish: bool = False

def load_settings() -> Settings:
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text())
            return Settings(**data)
        except Exception:
            pass
    return Settings()

def save_settings(settings: Settings) -> None:
    CONFIG_PATH.write_text(json.dumps(asdict(settings), indent=2))
