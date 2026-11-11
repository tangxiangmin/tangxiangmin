import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

TIMEZONE = "Asia/Shanghai"
START = "<!--START_SECTION:waka-->"
END = "<!--END_SECTION:waka-->"


def fetch_summary(date):
    query = urlencode({"start": date, "end": date, "timezone": TIMEZONE})
    token = os.environ.get("WAKATIME_ACCESS_TOKEN", "").strip()
    if not token:
        raise ValueError("WAKATIME_ACCESS_TOKEN is missing")
    request = Request(
        f"https://api.wakatime.com/api/v1/users/current/summaries?{query}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.load(response)
    days = payload.get("data")
    if not isinstance(days, list) or not days:
        raise ValueError("WakaTime returned no daily summaries")
    for day in days:
        if day["range"]["date"] == date.isoformat():
            return day
    raise ValueError("WakaTime did not return the requested date")


def format_tokens(value):
    return f"{value:,}" if type(value) is int and value >= 0 else "—"


def format_time(seconds):
    if type(seconds) not in (int, float) or seconds < 0:
        return "—"
    if 0 < seconds < 60:
        return "< 1m"
    hours, minutes = divmod(int(seconds) // 60, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def safe_name(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[\w .:/+()#-]+", value))


def reported_number(value):
    return value if type(value) in (int, float) and value >= 0 else 0


def time_distribution(days, field):
    totals = Counter()
    for day in days:
        for entry in day.get(field) or []:
            name = entry.get("name")
            if safe_name(name):
                totals[name] += reported_number(entry.get("total_seconds"))
    return totals


def ai_distribution(days):
    totals = Counter()
    for day in days:
        for entry in day.get("grand_total", {}).get("ai_model_breakdown") or []:
            name = entry.get("name")
            if safe_name(name):
                totals[name] += sum(
                    value for field in ("input_tokens", "output_tokens")
                    if type(value := entry.get(field)) is int and value >= 0
                )
    return totals


def distribution_table(title, column, unit, totals, format_value):
    total = sum(totals.values())
    if not total:
        return f"**{title}**\n\nNo usage reported."
    ordered = sorted(
        ((name, value) for name, value in totals.items() if value > 0),
        key=lambda item: (-item[1], item[0].casefold(), item[0]),
    )
    visible = ordered[:5]
    if len(ordered) > 5:
        visible.append(("Remaining", sum(value for _, value in ordered[5:])))
    rows = [
        f"**{title}**", "",
        f"| {column} | {unit} | Share |",
        "| --- | ---: | :--- |",
    ]
    for name, value in visible:
        share = value / total
        filled = max(1, round(share * 12))
        bar = "█" * filled + "░" * (12 - filled)
        rows.append(f"| {name} | {format_value(value)} | `{bar}` {share:.1%} |")
    return "\n".join(rows)


def render_summary(day, date):
    total = day.get("grand_total", {})
    duration = format_time(total.get("total_seconds"))
    inputs = format_tokens(total.get("ai_input_tokens"))
    outputs = format_tokens(total.get("ai_output_tokens"))
    overview = f"**Coding time** {duration} · **Input tokens** {inputs} · **Output tokens** {outputs}"
    return "\n\n".join([
        f"**{date.isoformat()} (UTC+8)**",
        overview,
        distribution_table("Languages", "Language", "Time", time_distribution([day], "languages"), format_time),
        distribution_table("Editors", "Editor", "Time", time_distribution([day], "editors"), format_time),
        distribution_table("AI usage by reported label", "AI label", "Input + output tokens", ai_distribution([day]), format_tokens),
    ])


def update_readme(path, summary):
    original = path.read_bytes().decode("utf-8")
    if original.count(START) != 1 or original.count(END) != 1:
        raise ValueError("README must contain exactly one WakaTime section")
    before, section = original.split(START, 1)
    if END not in section:
        raise ValueError("WakaTime section markers are out of order")
    _, after = section.split(END, 1)
    updated = f"{before}{START}\n\n{summary}\n\n{END}{after}"
    if updated != original:
        path.write_bytes(updated.encode("utf-8"))


def main():
    last_day = datetime.now(ZoneInfo(TIMEZONE)).date() - timedelta(days=1)
    try:
        day = fetch_summary(last_day)
        update_readme(Path("README.md"), render_summary(day, last_day))
    except HTTPError as error:
        print(f"WakaTime request failed with HTTP {error.code}", file=sys.stderr)
        return 1
    except URLError:
        print("Could not connect to WakaTime", file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError):
        print("Could not update the README. Check the OAuth token, daily summaries, and section markers.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
