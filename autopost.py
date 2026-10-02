#!/usr/bin/env python3
"""
HomePicksHQ — Automated Instagram Direct Publisher
Publishes 2-slide carousels directly to Instagram without Meta Business Suite.
"""

import os
import sys
import re
import json
import time
import getpass
from pathlib import Path
from PIL import Image, ImageFilter

try:
    from instagrapi import Client
    from instagrapi.exceptions import (
        LoginRequired,
        TwoFactorRequired,
        ChallengeRequired,
        BadPassword,
        PleaseWaitFewMinutes,
    )
except ImportError:
    print("❌ instagrapi is not installed. Run: pip install instagrapi pillow")
    sys.exit(1)

BASE_DIR = Path(__file__).resolve().parent
POSTS_FILE = BASE_DIR / "instagram-posts.md"
SESSION_FILE = BASE_DIR / "session.json"
HISTORY_FILE = BASE_DIR / "posted_history.json"
CACHE_DIR = BASE_DIR / "img_cache"


def load_history():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def parse_posts():
    """Parses all 26 posts from instagram-posts.md."""
    if not POSTS_FILE.exists():
        print(f"❌ Posts file not found: {POSTS_FILE}")
        return []

    with open(POSTS_FILE, "r", encoding="utf-8") as f:
        text = f.read()

    posts = []
    # Split by ## <num>.
    sections = re.split(r"\n##\s+(\d+)\.\s+", text)
    for i in range(1, len(sections), 2):
        post_id = int(sections[i])
        block = sections[i + 1]

        lines = block.strip().split("\n")
        title = lines[0].strip()

        # Image paths
        img_match = re.search(
            r"\*\s+\*\*Images\*\*:\s*`([^`]+)`(?:\s*\+\s*`([^`]+)`)?", block
        )
        img1_rel = img_match.group(1).strip() if img_match else ""
        img2_rel = img_match.group(2).strip() if (img_match and img_match.group(2)) else ""

        # Normalize relative image path (e.g. if checklist is just "checklist.jpg")
        if img1_rel and not (BASE_DIR / img1_rel).exists():
            # Try finding in img/
            if (BASE_DIR / "img" / Path(img1_rel).name).exists():
                img1_rel = f"img/{Path(img1_rel).name}"

        if img2_rel:
            if not (BASE_DIR / img2_rel).exists():
                # Derive checklist filename from hero if only 'checklist.jpg'
                if img2_rel == "checklist.jpg" and img1_rel:
                    candidate = img1_rel.replace("-hero.jpg", "-checklist.jpg")
                    if (BASE_DIR / candidate).exists():
                        img2_rel = candidate
                    else:
                        img2_rel = f"img/{Path(img2_rel).name}"
                else:
                    img2_rel = f"img/{Path(img2_rel).name}"

        # Extract Caption
        cap_match = re.search(r"\*\*Caption\*\*:\s*\n(.*?)(?=\n---\s*|\Z)", block, re.DOTALL)
        caption = cap_match.group(1).strip() if cap_match else ""

        posts.append(
            {
                "id": post_id,
                "title": title,
                "img1": img1_rel,
                "img2": img2_rel,
                "caption": caption,
            }
        )

    return posts


def prepare_carousel_slide(src_path: Path, output_path: Path, target_size=(1080, 1350)):
    """
    Fits any aspect ratio image into Instagram's 4:5 portrait frame (1080x1350)
    with a tasteful blurred background of the image itself.
    Ensures zero cropping of text and uniform aspect ratio for albums.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        return output_path

    with Image.open(src_path) as im:
        im = im.convert("RGB")
        tw, th = target_size

        # Background: cover and blur
        scale_bg = max(tw / im.width, th / im.height)
        bg_w = int(im.width * scale_bg)
        bg_h = int(im.height * scale_bg)
        bg = im.resize((bg_w, bg_h), Image.Resampling.LANCZOS)
        left = (bg_w - tw) // 2
        top = (bg_h - th) // 2
        bg = bg.crop((left, top, left + tw, top + th)).filter(ImageFilter.GaussianBlur(35))

        # Foreground: contain cleanly inside target canvas
        scale_fg = min(tw / im.width, th / im.height)
        fg_w = int(im.width * scale_fg)
        fg_h = int(im.height * scale_fg)
        fg = im.resize((fg_w, fg_h), Image.Resampling.LANCZOS)

        offset_x = (tw - fg_w) // 2
        offset_y = (th - fg_h) // 2
        bg.paste(fg, (offset_x, offset_y))

        bg.save(output_path, "JPEG", quality=95)

    return output_path


def get_instagram_client():
    """Initializes and authenticates the Instagram Client."""
    cl = Client()
    cl.delay_range = [2, 5]

    # Try loading saved session
    if SESSION_FILE.exists():
        try:
            print("🔑 Found saved session. Logging in...")
            cl.load_settings(SESSION_FILE)
            cl.get_timeline_feed()
            print("✅ Logged in successfully from saved session!")
            return cl
        except Exception as e:
            print(f"⚠️ Saved session expired or invalid ({e}). Please log in again.")
            SESSION_FILE.unlink(missing_ok=True)

    # Fresh login
    print("\n--- Instagram Authentication ---")
    print("ℹ️ Note: This connects directly to Instagram and does not use Meta Business Manager.")
    username = input("Enter your Instagram username: ").strip()
    password = getpass.getpass("Enter your Instagram password: ").strip()

    try:
        cl.login(username, password)
    except TwoFactorRequired:
        code = input("📱 Enter the 2-Factor Authentication (2FA) code from your app/SMS: ").strip()
        cl.login(username, password, verification_code=code)
    except ChallengeRequired:
        print("⚠️ Instagram requested a security challenge.")
        try:
            cl.challenge_resolve(cl.last_json)
        except Exception as ce:
            print(f"❌ Could not resolve challenge automatically: {ce}")
            sys.exit(1)
    except BadPassword:
        print("❌ Incorrect password.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Login error: {e}")
        sys.exit(1)

    # Save session
    try:
        cl.dump_settings(SESSION_FILE)
        print("💾 Session saved securely to session.json for future runs!")
    except Exception as e:
        print(f"⚠️ Warning: Could not save session: {e}")

    return cl


def publish_post(cl: Client, post: dict):
    """Formats images and uploads as a 2-slide carousel or single photo."""
    print(f"\n📤 Processing Post #{post['id']}: {post['title']}")

    slides = []
    # Slide 1 (Hero)
    if post["img1"]:
        src1 = BASE_DIR / post["img1"]
        if src1.exists():
            out1 = CACHE_DIR / f"post_{post['id']}_slide1.jpg"
            slides.append(prepare_carousel_slide(src1, out1))
        else:
            print(f"⚠️ Slide 1 not found at {src1}")

    # Slide 2 (Checklist)
    if post["img2"]:
        src2 = BASE_DIR / post["img2"]
        if src2.exists():
            out2 = CACHE_DIR / f"post_{post['id']}_slide2.jpg"
            slides.append(prepare_carousel_slide(src2, out2))
        else:
            print(f"ℹ️ Slide 2 not found at {src2} (posting as single image)")

    if not slides:
        print(f"❌ No valid images found for Post #{post['id']}. Skipping.")
        return None

    caption = post["caption"]

    try:
        if len(slides) > 1:
            print(f"📸 Uploading 2-slide carousel ({[s.name for s in slides]})...")
            media = cl.album_upload(slides, caption=caption)
        else:
            print(f"📸 Uploading single photo ({slides[0].name})...")
            media = cl.photo_upload(slides[0], caption=caption)

        print(f"🎉 SUCCESS! Published Post #{post['id']} (Media ID: {media.pk})")
        return media.pk
    except PleaseWaitFewMinutes:
        print("⚠️ Instagram rate limit hit: 'Please wait a few minutes'. Pausing...")
        return False
    except Exception as e:
        print(f"❌ Failed to publish Post #{post['id']}: {e}")
        return None


def main():
    print("=" * 60)
    print("    HomePicksHQ — Automated Instagram Direct Publisher    ")
    print("=" * 60)

    posts = parse_posts()
    if not posts:
        print("No posts found in instagram-posts.md.")
        return

    history = load_history()
    published_ids = set(int(k) for k in history.keys())

    print(f"📚 Loaded {len(posts)} total buying guides.")
    print(f"✅ Previously published: {len(published_ids)} / {len(posts)}")
    print(f"⏳ Remaining to publish: {len(posts) - len(published_ids)}")
    print("-" * 60)

    print("\nSelect an action:")
    print(" [1] Post a SINGLE guide (Test run — choose by number 1-26)")
    print(" [2] Post NEXT unpublished guide")
    print(" [3] Auto-publish ALL remaining guides with a scheduled interval")
    print(" [4] Preview list and publication status")
    print(" [5] Clear saved Instagram session")
    print(" [0] Exit")

    choice = input("\nEnter choice [0-5]: ").strip()

    if choice == "0":
        print("Goodbye!")
        return

    if choice == "4":
        print("\n--- All 26 Guides Status ---")
        for p in posts:
            status = "✅ PUBLISHED" if p["id"] in published_ids else "⏳ PENDING"
            print(f" #{p['id']:02d}: {p['title']} [{status}]")
        return

    if choice == "5":
        if SESSION_FILE.exists():
            SESSION_FILE.unlink()
            print("🗑️ Cleared session.json. Next run will require login.")
        else:
            print("No saved session found.")
        return

    # Requires Instagram Login
    cl = get_instagram_client()

    if choice == "1":
        num_str = input(f"Enter guide number to publish (1-{len(posts)}): ").strip()
        try:
            target_id = int(num_str)
            target_post = next((p for p in posts if p["id"] == target_id), None)
            if not target_post:
                print(f"❌ Post #{target_id} not found.")
                return
            media_id = publish_post(cl, target_post)
            if media_id:
                history[str(target_id)] = {
                    "title": target_post["title"],
                    "media_id": str(media_id),
                    "published_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                save_history(history)
        except ValueError:
            print("Invalid number.")

    elif choice == "2":
        next_post = next((p for p in posts if p["id"] not in published_ids), None)
        if not next_post:
            print("🎉 All 26 posts have already been published!")
            return
        media_id = publish_post(cl, next_post)
        if media_id:
            history[str(next_post["id"])] = {
                "title": next_post["title"],
                "media_id": str(media_id),
                "published_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            save_history(history)

    elif choice == "3":
        pending_posts = [p for p in posts if p["id"] not in published_ids]
        if not pending_posts:
            print("🎉 All 26 posts have already been published!")
            return

        print(f"\nFound {len(pending_posts)} pending posts.")
        hours_str = input("Enter delay between posts in HOURS (e.g., 4 or 6, recommended min 3): ").strip()
        try:
            delay_hours = float(hours_str) if hours_str else 4.0
        except ValueError:
            delay_hours = 4.0

        delay_seconds = int(delay_hours * 3600)
        print(f"⏰ Scheduler active: Posting 1 guide every {delay_hours} hours ({delay_seconds} seconds).")
        print("Press Ctrl+C at any time to stop safely.\n")

        for idx, post in enumerate(pending_posts):
            media_id = publish_post(cl, post)
            if media_id:
                history[str(post["id"])] = {
                    "title": post["title"],
                    "media_id": str(media_id),
                    "published_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                save_history(history)

            # If not the last post, wait
            if idx < len(pending_posts) - 1:
                next_time = time.strftime("%H:%M:%S", time.localtime(time.time() + delay_seconds))
                print(f"⏳ Waiting {delay_hours} hours. Next post at {next_time}...")
                time.sleep(delay_seconds)

        print("\n🎉 Completed all scheduled posts!")


if __name__ == "__main__":
    main()
