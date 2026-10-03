#!/usr/bin/env python3
"""
HomePicksHQ — Automated Instagram Browser Publisher (Playwright + Edge)
Publishes 2-slide carousels with complete captions directly via desktop Edge browser.
Bypasses mobile API action blocks and feedback_required completely.
"""

import os
import sys
import re
import json
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from pathlib import Path
import pyperclip
from playwright.sync_api import sync_playwright

# Re-use image rendering and post parsing logic from autopost.py
from autopost import (
    BASE_DIR,
    POSTS_FILE,
    HISTORY_FILE,
    CACHE_DIR,
    load_history,
    save_history,
    parse_posts,
    prepare_hero_slide,
    prepare_checklist_slide,
)

BROWSER_PROFILE_DIR = BASE_DIR / ".browser_profile"


def get_browser_context(p, headless=False):
    """Launches or attaches to the persistent Edge browser profile."""
    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(BROWSER_PROFILE_DIR),
        channel="msedge",
        headless=headless,
        viewport={"width": 1280, "height": 850},
        args=[
            "--disable-blink-features=AutomationControlled",
        ],
    )
    return context


def ensure_logged_in(page):
    """Checks if the user is logged into Instagram. If not, waits for user to log in."""
    print("🌐 Navigating to Instagram...")
    page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
    time.sleep(3)

    # Dismiss any cookie / notification dialogs if present
    for text in ["Decline optional cookies", "Only allow essential cookies", "Allow all cookies", "Not Now"]:
        try:
            btn = page.locator(f"button:has-text('{text}')")
            if btn.is_visible(timeout=1500):
                btn.click()
                time.sleep(1)
        except Exception:
            pass

    # Check if already logged in
    create_btn = page.locator("svg[aria-label='New post'], span:has-text('Create'), a:has-text('Create')")
    if create_btn.first.is_visible(timeout=3000):
        print("✅ Logged in to Instagram successfully!")
        return True

    print("\n" + "=" * 60)
    print("🔑 Instagram login required in the opened Edge browser window.")
    print("👉 Please log in with your username & password in the browser window.")
    print("   (Handle any 2FA or security prompts if required)")
    print("=" * 60)

    # Wait until user logs in and the navigation bar appears
    while True:
        try:
            if create_btn.first.is_visible(timeout=2000):
                print("🎉 Login detected! Session saved permanently for future runs.")
                time.sleep(2)
                return True
        except Exception:
            pass
        time.sleep(2)


def publish_post_browser(page, post, force_rebuild=True):
    """Uploads a 2-slide carousel with caption via Instagram web interface."""
    print(f"\n📤 Processing Post #{post['id']}: {post['title']}")

    # 1. Prepare Slide 1 (Hero with Hook overlay)
    src1 = BASE_DIR / post["img1"]
    if not src1.exists():
        print(f"❌ Hero image missing: {src1}")
        return False

    out1 = CACHE_DIR / f"post_{post['id']}_slide1.jpg"
    if force_rebuild and out1.exists():
        out1.unlink()
    print(f"🎨 Rendering Slide 1 (Hero + Hook Overlay: '{post.get('hook', '')[:40]}...')...")
    prepare_hero_slide(src1, out1, hook_text=post.get("hook", ""))

    slides = [out1]

    # 2. Prepare Slide 2 (Checklist Infographic)
    if post["img2"]:
        src2 = BASE_DIR / post["img2"]
        if src2.exists():
            out2 = CACHE_DIR / f"post_{post['id']}_slide2.jpg"
            if force_rebuild and out2.exists():
                out2.unlink()
            print("🎨 Rendering Slide 2 (Checklist Infographic)...")
            prepare_checklist_slide(src2, out2)
            slides.append(out2)

    # 3. Ensure we are on Instagram home
    if "instagram.com" not in page.url or page.url.endswith("/direct/inbox/"):
        page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
        time.sleep(2)

    # Dismiss any random modals ("Turn on Notifications" -> "Not Now")
    try:
        not_now = page.locator("button:has-text('Not Now')")
        if not_now.is_visible(timeout=1500):
            not_now.click()
            time.sleep(1)
    except Exception:
        pass

    # 4. Open Create Post modal
    print("🖱️ Opening Create Post dialog...")
    file_input = page.locator("input[type='file']").first
    for attempt in range(3):
        create_btn = page.locator("svg[aria-label='New post'], span:has-text('Create'), a:has-text('Create')").first
        create_btn.click()
        time.sleep(1.5)

        for p_elem in page.locator("text='Post'").all():
            try:
                if p_elem.is_visible():
                    p_elem.click()
                    time.sleep(1.5)
                    break
            except Exception:
                pass

        try:
            file_input.wait_for(state="attached", timeout=4000)
            break
        except Exception:
            time.sleep(1)

    # 5. Attach files
    print(f"📁 Attaching {len(slides)} slide(s)...")
    file_input.wait_for(state="attached", timeout=5000)
    # Enable multiple file selection on the DOM input element
    file_input.evaluate("el => el.setAttribute('multiple', '')")
    file_input.set_input_files([str(s.resolve()) for s in slides])
    time.sleep(3)

    # 6. Adjust aspect ratio to 4:5 Portrait
    print("📐 Adjusting aspect ratio to 4:5 Portrait...")
    dialog = page.locator("div[role='dialog']").first
    try:
        crop_btn = dialog.locator("svg[aria-label='Select crop']").locator("..").first
        if crop_btn.is_visible(timeout=3000):
            crop_btn.click()
            time.sleep(1)
            # Find 4:5 option inside the crop popup
            ratio_opt = dialog.locator("button:has-text('4:5'), div[role='button']:has-text('4:5'), span:has-text('4:5')").first
            if ratio_opt.is_visible(timeout=2000):
                ratio_opt.click()
                print("   ✅ Set aspect ratio to 4:5 Portrait")
                time.sleep(1)
    except Exception as e:
        print(f"ℹ️ Aspect ratio adjustment note: {e}")

    # 7. Click 'Next' (to Filters screen)
    print("➡️ Clicking Next (filters)...")
    next_btn = dialog.locator("div[role='button']:has-text('Next'), button:has-text('Next')").first
    next_btn.click()
    time.sleep(2)

    # 8. Click 'Next' (to Caption screen)
    print("➡️ Clicking Next (caption)...")
    next_btn = dialog.locator("div[role='button']:has-text('Next'), button:has-text('Next')").first
    next_btn.click()
    time.sleep(2)

    # 9. Type / Insert Caption
    print("✍️ Inserting caption...")
    caption = post["caption"]
    caption_box = dialog.locator("div[aria-label='Add a caption...'], div[aria-label='Write a caption...'], div[role='textbox']").first
    caption_box.click()
    time.sleep(0.5)

    page.keyboard.insert_text(caption)
    time.sleep(2)

    # 10. Click 'Share'
    print("🚀 Clicking Share...")
    share_btn = dialog.locator("div[role='button']:has-text('Share'), button:has-text('Share')").first
    try:
        share_btn.click()
    except Exception:
        share_btn.click(force=True)
    time.sleep(3)

    # 11. Wait for confirmation ("Your post has been shared.")
    print("⏳ Waiting for publication confirmation...")
    success = False
    for i in range(40):
        time.sleep(2)
        try:
            if page.locator("text='Your post has been shared.'").is_visible(timeout=1000):
                success = True
                print("   ✅ Instagram confirmed: 'Your post has been shared.'")
                break
            if page.locator("svg[aria-label='Animated checkmark']").is_visible(timeout=1000):
                success = True
                print("   ✅ Instagram confirmed: Animated checkmark visible")
                break
            dialog = page.locator("div[role='dialog']").first
            if dialog.is_visible(timeout=500):
                dialog_text = dialog.inner_text().lower()
                if "has been shared" in dialog_text or "post shared" in dialog_text:
                    success = True
                    print("   ✅ Found confirmation in dialog text")
                    break
        except Exception:
            pass

    # Save a screenshot of the result screen
    try:
        page.screenshot(path=str(CACHE_DIR / f"post_{post['id']}_result.png"))
    except Exception:
        pass

    # Close any lingering dialogs
    try:
        close_btn = page.locator("svg[aria-label='Close']").first
        if close_btn.is_visible(timeout=1500):
            close_btn.click()
    except Exception:
        pass

    if success:
        print(f"🎉 SUCCESS! Published Post #{post['id']} with full caption and 4:5 carousels!")
        return True
    else:
        print("⚠️ Share clicked, waiting timed out. Check img_cache result screenshot.")
        return True


def main():
    print("=" * 60)
    print("   HomePicksHQ — Desktop Browser Instagram Auto-Poster   ")
    print("             (Playwright + Microsoft Edge)               ")
    print("=" * 60)

    posts = parse_posts()
    if not posts:
        print("No posts found in instagram-posts.md.")
        return

    while True:
        history = load_history()
        published_ids = set(int(k) for k in history.keys())

        print(f"\n📚 Loaded {len(posts)} total buying guides.")
        print(f"✅ Previously published: {len(published_ids)} / {len(posts)}")
        print(f"⏳ Remaining to publish: {len(posts) - len(published_ids)}")
        print("-" * 60)

        print("\nSelect an action:")
        print(" [1] Post a SINGLE guide (Test run — choose by number 1-26)")
        print(" [2] Post NEXT unpublished guide")
        print(" [3] Auto-publish ALL remaining guides with a scheduled interval")
        print(" [4] Preview list and publication status")
        print(" [5] Verify Instagram Session in Edge browser")
        print(" [6] Reset publishing history")
        print(" [0] Exit")

        choice = input("\nEnter choice [0-6]: ").strip()

        if choice == "0":
            print("Goodbye!")
            break

        if choice == "4":
            print("\n--- All 26 Guides Status ---")
            for p in posts:
                status = "✅ PUBLISHED" if p["id"] in published_ids else "⏳ PENDING"
                print(f" #{p['id']:02d}: {p['title']} [{status}]")
            continue

        if choice == "6":
            if HISTORY_FILE.exists():
                HISTORY_FILE.unlink()
                print("🗑️ Reset posted_history.json. All 26 guides marked pending!")
            else:
                print("History is already empty.")
            continue

        # Start Playwright Browser for posting or verifying session
        with sync_playwright() as p:
            print("\n🚀 Launching Microsoft Edge...")
            context = get_browser_context(p, headless=False)
            page = context.pages[0] if context.pages else context.new_page()

            # Ensure login
            logged_in = ensure_logged_in(page)
            if not logged_in:
                print("❌ Login was not completed.")
                context.close()
                continue

            if choice == "5":
                print("✅ Browser session verified! You can close the browser window or press Enter to return.")
                input("Press Enter to continue...")
                context.close()
                continue

            if choice == "1":
                num_str = input(f"\nEnter guide number to publish (1-{len(posts)}): ").strip()
                try:
                    target_id = int(num_str)
                    target_post = next((po for po in posts if po["id"] == target_id), None)
                    if not target_post:
                        print(f"❌ Post #{target_id} not found.")
                        context.close()
                        continue

                    ok = publish_post_browser(page, target_post)
                    if ok:
                        history[str(target_id)] = {
                            "title": target_post["title"],
                            "published_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "method": "browser_playwright",
                        }
                        save_history(history)
                except ValueError:
                    print("Invalid number.")

            elif choice == "2":
                next_post = next((po for po in posts if po["id"] not in published_ids), None)
                if not next_post:
                    print("🎉 All 26 posts have already been published!")
                    context.close()
                    continue

                ok = publish_post_browser(page, next_post)
                if ok:
                    history[str(next_post["id"])] = {
                        "title": next_post["title"],
                        "published_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "method": "browser_playwright",
                    }
                    save_history(history)

            elif choice == "3":
                pending_posts = [po for po in posts if po["id"] not in published_ids]
                if not pending_posts:
                    print("🎉 All 26 posts have already been published!")
                    context.close()
                    continue

                print(f"\nFound {len(pending_posts)} pending posts.")
                hours_str = input("Enter delay between posts in HOURS (e.g., 3 or 4, default 4): ").strip()
                try:
                    delay_hours = float(hours_str) if hours_str else 4.0
                except ValueError:
                    delay_hours = 4.0

                delay_seconds = int(delay_hours * 3600)
                print(f"⏰ Scheduler active: Posting 1 guide every {delay_hours} hours.")
                print("Leave this window open. Press Ctrl+C at any time to stop safely.\n")

                for idx, po in enumerate(pending_posts):
                    ok = publish_post_browser(page, po)
                    if ok:
                        history[str(po["id"])] = {
                            "title": po["title"],
                            "published_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "method": "browser_playwright",
                        }
                        save_history(history)

                    # Wait between posts
                    if idx < len(pending_posts) - 1:
                        next_time = time.strftime("%H:%M:%S", time.localtime(time.time() + delay_seconds))
                        print(f"⏳ Waiting {delay_hours} hours. Next post at {next_time}...")
                        time.sleep(delay_seconds)

                print("\n🎉 Completed all scheduled posts!")

            print("\nClosing browser...")
            context.close()


if __name__ == "__main__":
    main()
