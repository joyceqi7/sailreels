"""Media pipeline CLI — drives the drama lifecycle without waiting for Celery.

Examples:
  uv run python -m scripts.media list
  uv run python -m scripts.media upload-videos <drama_id>      # queue + poll all episode uploads
  uv run python -m scripts.media push <drama_id>              # new album version, writes episode_id back
  uv run python -m scripts.media submit <drama_id>            # send to review
  uv run python -m scripts.media status <drama_id>            # poll review/publish state
  uv run python -m scripts.media go-live <drama_id>           # set online version + publish
  uv run python -m scripts.media add-drama --title ... --source-dir ./eps --cover-url ...
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Drama, Episode
from app.services import media
from app.tiktok.client import TikTokClient


def _client() -> TikTokClient:
    from app.core.config import get_settings
    return TikTokClient(get_settings())


async def _get_drama(session, drama_id: int) -> Drama:
    drama = await session.get(Drama, drama_id)
    if drama is None:
        sys.exit(f"drama {drama_id} not found")
    return drama


async def cmd_list(_args) -> None:
    async with SessionLocal() as session:
        dramas = (await session.scalars(select(Drama).order_by(Drama.id))).all()
        for d in dramas:
            eps = len(list(await session.scalars(select(Episode).where(Episode.drama_id == d.id))))
            print(f"id={d.id} album_id={d.album_id} ver={d.current_version}/{d.online_version} "
                  f"review={d.review_status} publish={d.publish_status} eps={eps} {d.title}")


async def cmd_add_drama(args) -> None:
    """Create a drama from a directory of episode files named 01.mp4, 02.mp4, ... """
    files = sorted(await asyncio.to_thread(lambda: list(Path(args.source_dir).glob("*.mp4"))))
    if not files:
        sys.exit(f"no .mp4 files in {args.source_dir}")
    async with SessionLocal() as session:
        drama = Drama(
            title=args.title, description=args.description, language=args.language,
            year=args.year, drama_type=args.drama_type, tags=args.tags,
            total_episodes=len(files), free_episodes=args.free_episodes,
            unlock_price_beans=args.unlock_price_beans, cover_url=args.cover_url or "",
        )
        session.add(drama)
        await session.flush()
        for i, path in enumerate(files, start=1):
            session.add(Episode(drama_id=drama.id, seq=i, title=f"EP{i}", source_url=args.url_prefix + path.name))
        await session.commit()
        print(f"created drama {drama.id} with {len(files)} episodes")


async def cmd_upload_covers(args) -> None:
    client = _client()
    async with SessionLocal() as session:
        drama = await _get_drama(session, args.drama_id)
        for url in args.url:
            pic_id = await media.upload_image(session, client, url)
            drama.cover_pic_ids = [*drama.cover_pic_ids, pic_id]
            await session.commit()
            print(f"cover -> {pic_id}")


async def cmd_upload_episode_covers(args) -> None:
    """Every episode needs its own cover_list before album/update will accept it.

    Two modes: pass one --url to reuse it for all episodes without a cover, or pass --cover-dir of
    01.jpg/02.jpg/... to pair by episode number. Already-covered episodes are skipped unless --force.
    """
    client = _client()
    async with SessionLocal() as session:
        drama = await _get_drama(session, args.drama_id)
        episodes = list(await session.scalars(
            select(Episode).where(Episode.drama_id == drama.id).order_by(Episode.seq)))

        if args.cover_dir and args.url:
            sys.exit("pass either --cover-dir or --url, not both")

        if args.cover_dir:
            directory = Path(args.cover_dir)
            by_seq: dict[int, Path] = {}
            for path in sorted(await asyncio.to_thread(lambda: list(directory.iterdir()))):
                if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
                    continue
                try:
                    by_seq[int(path.stem)] = path
                except ValueError:
                    continue
            if not by_seq:
                sys.exit(f"no 01.jpg-style cover files in {directory}")
            targets = [(ep, args.url_prefix + by_seq[ep.seq].name)
                       for ep in episodes if ep.seq in by_seq]
            missing = [ep.seq for ep in episodes if ep.seq not in by_seq]
            if missing:
                sys.exit(f"missing cover files for episodes {missing}; expected {{n}}.jpg in {directory}")
        elif args.url:
            targets = [(ep, args.url) for ep in episodes]
        else:
            sys.exit("pass --cover-dir or --url")

        for ep, url in targets:
            if ep.cover_pic_id and not args.force:
                continue
            ep.cover_pic_id = await media.upload_image(session, client, url)
            ep.cover_url = url
            await session.commit()
            print(f"EP{ep.seq} cover -> {ep.cover_pic_id}")

        missing = [ep.seq for ep in episodes if not ep.cover_pic_id]
        if missing:
            sys.exit(f"episodes still without a cover: {missing}")


async def cmd_submit(args) -> None:
    client = _client()
    async with SessionLocal() as session:
        drama = await _get_drama(session, args.drama_id)
        review_id = await media.submit_review(session, client, drama)
        print(f"review_id={review_id} version={drama.current_version}")


async def cmd_upload_videos(args) -> None:
    client = _client()
    async with SessionLocal() as session:
        drama = await _get_drama(session, args.drama_id)
        episodes = list(await session.scalars(
            select(Episode).where(Episode.drama_id == drama.id).order_by(Episode.seq)))
        for ep in episodes:
            if ep.vid:
                continue
            job_id = await media.upload_episode_video(session, client, ep, drama)
            print(f"EP{ep.seq} queued job={job_id}")
        vids = await media.wait_for_videos(session, client, drama)
        print(json.dumps({f"EP{k}": v for k, v in sorted(vids.items())}, indent=2))
        missing = [e.seq for e in episodes if not e.vid]
        if missing:
            print(f"WARNING: no vid for episodes {missing}", file=sys.stderr)


async def cmd_push(args) -> None:
    client = _client()
    async with SessionLocal() as session:
        drama = await _get_drama(session, args.drama_id)
        version = await media.push_album(session, client, drama)
        print(f"version={version}")
        for ep in await media.list_episodes(session, drama):
            print(f"  EP{ep.seq} episode_id={ep.episode_id} vid={ep.vid}")


async def cmd_status(args) -> None:
    client = _client()
    async with SessionLocal() as session:
        drama = await _get_drama(session, args.drama_id)
        print(json.dumps(await media.sync_status(session, client, drama), indent=2, ensure_ascii=False))


async def cmd_go_live(args) -> None:
    client = _client()
    async with SessionLocal() as session:
        drama = await _get_drama(session, args.drama_id)
        await media.go_live(session, client, drama)
        print(f"live: album={drama.album_id} version={drama.online_version}")


async def cmd_authorize(args) -> None:
    """Lend this album to another app under the same entity (usually supplier app -> our app)."""
    client = _client()
    async with SessionLocal() as session:
        drama = await _get_drama(session, args.drama_id)
        data = await media.authorize_to_apps(
            session, client, drama, args.client_key, operate_type=args.operate_type)
        for row in data.get("client_key_result_list", []):
            print(f"{row.get('client_key')}: auth_status={row.get('auth_status')}")


async def cmd_appeal(args) -> None:
    client = _client()
    async with SessionLocal() as session:
        drama = await _get_drama(session, args.drama_id)
        await media.appeal_rejection(
            session, client, drama, reason=args.reason, seq=args.seq,
            attachment_urls=args.attachment)
        print(f"appeal submitted for {'album' if args.seq is None else f'EP{args.seq}'}")


def main() -> None:
    p = argparse.ArgumentParser(prog="media")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(fn=cmd_list)

    a = sub.add_parser("add-drama")
    a.add_argument("--title", required=True)
    a.add_argument("--description", default="")
    a.add_argument("--source-dir", required=True, help="directory of 01.mp4, 02.mp4, ...")
    a.add_argument("--url-prefix", required=True, help="public URL prefix these files are served from")
    a.add_argument("--cover-url")
    a.add_argument("--language", default="en")
    a.add_argument("--year", type=int, default=2026)
    a.add_argument("--drama-type", type=int, default=4, help="1 AIGC, 2 anime, 3 dubbed, 4 localised")
    a.add_argument("--tags", type=int, nargs="+", default=[13], help="1-3 tags, 1..46 (no 32)")
    a.add_argument("--free-episodes", type=int, default=5)
    a.add_argument("--unlock-price-beans", type=int, default=100)
    a.set_defaults(fn=cmd_add_drama)

    a = sub.add_parser("upload-covers")
    a.add_argument("drama_id", type=int)
    a.add_argument("--url", nargs="+", required=True)
    a.set_defaults(fn=cmd_upload_covers)

    a = sub.add_parser("upload-episode-covers",
                       help="episode cover_list is required on every album/update")
    a.add_argument("drama_id", type=int)
    a.add_argument("--cover-dir", help="directory of 01.jpg, 02.jpg, ... paired by episode number")
    a.add_argument("--url", help="one URL reused for every episode that has no cover")
    a.add_argument("--url-prefix", default="", help="prefix for filenames from --cover-dir")
    a.add_argument("--force", action="store_true", help="re-upload even if a cover is already set")
    a.set_defaults(fn=cmd_upload_episode_covers)

    a = sub.add_parser("upload-videos")
    a.add_argument("drama_id", type=int)
    a.set_defaults(fn=cmd_upload_videos)

    a = sub.add_parser("push")
    a.add_argument("drama_id", type=int)
    a.set_defaults(fn=cmd_push)

    a = sub.add_parser("submit")
    a.add_argument("drama_id", type=int)
    a.set_defaults(fn=cmd_submit)

    a = sub.add_parser("status")
    a.add_argument("drama_id", type=int)
    a.set_defaults(fn=cmd_status)

    a = sub.add_parser("go-live")
    a.add_argument("drama_id", type=int)
    a.set_defaults(fn=cmd_go_live)

    a = sub.add_parser("authorize", help="lend this album to another Minis app (same entity)")
    a.add_argument("drama_id", type=int)
    a.add_argument("--client-key", nargs="+", required=True, help="target app client_key(s)")
    a.add_argument("--operate-type", type=int, default=1, choices=[1, 2], help="1 grant, 2 revoke")
    a.set_defaults(fn=cmd_authorize)

    a = sub.add_parser("appeal", help="appeal a rejected album or episode")
    a.add_argument("drama_id", type=int)
    a.add_argument("--reason", required=True)
    a.add_argument("--seq", type=int, help="appeal this episode instead of the whole album")
    a.add_argument("--attachment", nargs="*", help="attachment URLs (max 10)")
    a.set_defaults(fn=cmd_appeal)

    args = p.parse_args()
    asyncio.run(args.fn(args))


if __name__ == "__main__":
    main()
