"""Seed the official TikTok test drama so the player can be integrated before our own content passes review.

album_id/episode_id/vid come from docs/official/13-player-integration.md and the official demo.
Usage: uv run python -m scripts.seed_test_drama
"""

import asyncio

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Drama, Episode

ALBUM_ID = "7667061213232384021"
EPISODES = [
    ("7667063938195015688", "v25b3bgm0018d9jgcu2tgd62dtifvgc0"),
    ("7667063938195032072", "v25b3bgm0018d9jgdaqtgd63istgth3g"),
    ("7667063938195048456", "v18b3bgm0018d9jgdjatgd606dirdp0g"),
]


async def main() -> None:
    async with SessionLocal() as s:
        if await s.scalar(select(Drama).where(Drama.album_id == ALBUM_ID)):
            print("already seeded")
            return
        drama = Drama(album_id=ALBUM_ID, title="Official Test Drama", total_episodes=len(EPISODES),
                      free_episodes=1, unlock_price_beans=100, review_status=2, publish_status=1)
        s.add(drama)
        await s.flush()
        for i, (episode_id, vid) in enumerate(EPISODES, start=1):
            s.add(Episode(drama_id=drama.id, seq=i, title=f"EP{i}", episode_id=episode_id, vid=vid))
        await s.commit()
        print(f"seeded drama id={drama.id}")


if __name__ == "__main__":
    asyncio.run(main())
