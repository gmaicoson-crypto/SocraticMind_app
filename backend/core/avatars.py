import secrets
from pathlib import Path


PRESET_ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "avatars"

USER_AVATAR_NAMES = (
    "girl-journal",
    "boy-sketch",
    "girl-poetry",
    "boy-write",
    "girl-botany",
    "boy-insects",
    "boy-read",
    "boy-calligraphy",
    "boy-astronomy",
    "girl-globe",
    "boy-geometry",
    "girl-read",
    "boy-math",
    "girl-handwriting",
    "boy-atlas",
    "girl-music",
    "girl-butterfly",
    "girl-write",
    "girl-flashcards",
    "boy-dictionary",
)
USER_AVATAR_PRESETS = tuple(f"/avatars/study/{name}.webp" for name in USER_AVATAR_NAMES)
AI_AVATAR_PRESETS = frozenset(
    f"/avatars/AI/study/AI-{gender}-{index}.webp"
    for gender in ("female", "male")
    for index in range(1, 4)
) | frozenset(
    f"/avatars/AI/normal/AI_normal{f'_{index}' if index > 1 else ''}.webp" for index in range(1, 7)
)
DEFAULT_AI_AVATAR = "/avatars/AI/study/AI-male-1.webp"


def choose_user_avatar() -> str:
    return secrets.choice(USER_AVATAR_PRESETS)
