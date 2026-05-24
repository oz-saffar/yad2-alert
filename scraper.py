import json
import os
import sys
import requests

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SEEN_FILE = "seen_ids.json"

YAD2_API = "https://gw.yad2.co.il/feed-search-legacy/realestate/rent"
YAD2_PARAMS = {
    "property": "3,5,6,39,32,55",
    "area": "52",
    "city": "0166",
    "forceLdLoad": "true",
}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    "mainSite": "yad2",
    "Referer": "https://www.yad2.co.il/",
    "Origin": "https://www.yad2.co.il",
}


def fetch_listings():
    resp = requests.get(YAD2_API, params=YAD2_PARAMS, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data["data"]["feed"]["feed_items"]


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
        timeout=15,
    )
    resp.raise_for_status()


def load_seen():
    try:
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(sorted(seen), f)


def format_message(item):
    lid = item["id"]
    title = item.get("title_1", "") or item.get("title", "")
    subtitle = item.get("title_2", "") or item.get("subtitle", "")
    price = item.get("price", "")
    city = item.get("city_text", "")
    neighborhood = item.get("neighborhood_text", "")
    rooms = item.get("Rooms_text", item.get("rooms", ""))
    floor = item.get("floor_text", "")

    location = ", ".join(filter(None, [city, neighborhood]))
    details = " | ".join(filter(None, [rooms, floor]))
    link = f"https://www.yad2.co.il/item/{lid}"

    lines = [f"<b>🏠 דירה חדשה!</b>"]
    if title:
        lines.append(title)
    if subtitle:
        lines.append(subtitle)
    if location:
        lines.append(f"📍 {location}")
    if details:
        lines.append(f"ℹ️ {details}")
    if price:
        lines.append(f"💰 {price}")
    lines.append(f'<a href="{link}">לפרסום ביד2</a>')
    return "\n".join(lines)


def main():
    seen = load_seen()

    try:
        items = fetch_listings()
    except requests.HTTPError as e:
        print(f"HTTP error fetching listings: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error fetching listings: {e}", file=sys.stderr)
        sys.exit(1)

    new_count = 0
    for item in items:
        if item.get("type") not in ("ad", "platinum"):
            continue
        lid = str(item.get("id", ""))
        if not lid or lid in seen:
            continue

        seen.add(lid)
        msg = format_message(item)
        try:
            send_telegram(msg)
            print(f"Sent alert for listing {lid}")
            new_count += 1
        except Exception as e:
            print(f"Failed to send Telegram for {lid}: {e}", file=sys.stderr)

    save_seen(seen)
    print(f"Done. {new_count} new listing(s) found.")


if __name__ == "__main__":
    main()
