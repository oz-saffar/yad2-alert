import json
import os
import sys
import time
import requests

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SEEN_FILE = "seen_ids.json"

YAD2_API = "https://gw.yad2.co.il/realestate-feed/rent/feed"
YAD2_PARAMS = {
    "region": "2",
    "area": "52",
    "city": "0166",
    "property": "3,5,6,39,32,55",
}
SEARCH_URL = (
    "https://www.yad2.co.il/realestate/rent/south"
    "?property=3%2C5%2C6%2C39%2C32%2C55&area=52&city=0166"
)
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
API_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.yad2.co.il/realestate/rent",
    "Origin": "https://www.yad2.co.il",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

ITEM_BUCKETS = ("platinum", "private", "agency")


def _make_session():
    session = requests.Session()
    # Warm up cookies by hitting the public search page first. The Yad2 WAF
    # (Reblaze, sets __uzm* cookies) returns HTML challenge pages to bare API
    # requests from cloud IPs, but accepts requests once the session has the
    # tokens it issues from a regular page load.
    session.get(SEARCH_URL, headers=BROWSER_HEADERS, timeout=30)
    return session


def fetch_listings():
    items = []
    page = 1
    session = _make_session()
    while True:
        params = {**YAD2_PARAMS, "page": str(page)}
        resp = session.get(YAD2_API, params=params, headers=API_HEADERS, timeout=30)
        resp.raise_for_status()
        try:
            payload = resp.json()
        except ValueError:
            snippet = resp.text[:200].replace("\n", " ")
            raise RuntimeError(
                f"Non-JSON response from Yad2 (status {resp.status_code}): {snippet}"
            )
        data = payload.get("data", {})
        for bucket in ITEM_BUCKETS:
            bucket_items = data.get(bucket) or []
            if isinstance(bucket_items, list):
                items.extend(bucket_items)
        pagination = data.get("pagination") or {}
        total_pages = pagination.get("totalPages", 1)
        if page >= total_pages:
            break
        page += 1
    return items


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
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


def _get(d, *path, default=""):
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur if cur is not None else default


def format_message(item):
    token = item.get("token", "")
    address = item.get("address", {}) or {}
    details = item.get("additionalDetails", {}) or {}

    city = _get(address, "city", "text")
    neighborhood = _get(address, "neighborhood", "text")
    street = _get(address, "street", "text")
    house_num = _get(address, "house", "number")
    floor = _get(address, "house", "floor")

    prop_type = _get(details, "property", "text")
    rooms = details.get("roomsCount", "")
    sqm = details.get("squareMeter", "")
    price = item.get("price", "")

    street_line = street
    if street and house_num:
        street_line = f"{street} {house_num}"

    location = ", ".join(filter(None, [neighborhood, city]))
    info_parts = []
    if prop_type:
        info_parts.append(str(prop_type))
    if rooms:
        info_parts.append(f"{rooms} חד'")
    if sqm:
        info_parts.append(f"{sqm} מ\"ר")
    if floor not in ("", None):
        info_parts.append(f"קומה {floor}")

    link = f"https://www.yad2.co.il/realestate/item/{token}"
    lines = ["<b>🏠 דירה חדשה!</b>"]
    if street_line:
        lines.append(street_line)
    if location:
        lines.append(f"📍 {location}")
    if info_parts:
        lines.append("ℹ️ " + " | ".join(info_parts))
    if price:
        lines.append(f"💰 {price:,} ₪".replace(",", ","))
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

    print(f"Fetched {len(items)} listing(s) from Yad2.")

    new_count = 0
    for item in items:
        token = str(item.get("token", ""))
        if not token or token in seen:
            continue

        seen.add(token)
        msg = format_message(item)
        try:
            send_telegram(msg)
            print(f"Sent alert for listing {token}")
            new_count += 1
            time.sleep(1.2)
        except Exception as e:
            print(f"Failed to send Telegram for {token}: {e}", file=sys.stderr)

    save_seen(seen)
    print(f"Done. {new_count} new listing(s) found.")


if __name__ == "__main__":
    main()
