import re
from datetime import datetime, date, timedelta
from collections import defaultdict
import streamlit as st


# -----------------------------
# Regex patterns
# -----------------------------

# Accept puzzle numbers like 1689 or 1,689
WORDLE_PAT = re.compile(
    r"\bWordle\s+(?P<puzzle>[\d,]+)\s+(?P<result>([1-6]/6|X/6))",
    re.IGNORECASE,
)

# Accept times with or without seconds
LINE_PATS = [
    re.compile(
        r"^(?P<d>\d{1,2}/\d{1,2}/\d{2,4}), (?P<t>\d{1,2}:\d{2}(?::\d{2})?) - (?P<name>.*?): (?P<msg>.*)$"
    ),
    re.compile(
        r"^\[(?P<d>\d{1,2}/\d{1,2}/\d{2,4}), (?P<t>\d{1,2}:\d{2}(?::\d{2})?)\] (?P<name>.*?): (?P<msg>.*)$"
    ),
]


# -----------------------------
# Helpers
# -----------------------------

def parse_dt(d_str: str, t_str: str, prefer_dmy: bool) -> datetime:
    """Parse WhatsApp export date + time."""
    if prefer_dmy:
        fmts = ["%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y", "%m/%d/%y"]
    else:
        fmts = ["%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%d/%m/%y"]

    parsed_date = None
    for fmt in fmts:
        try:
            parsed_date = datetime.strptime(d_str, fmt).date()
            break
        except ValueError:
            continue

    if parsed_date is None:
        raise ValueError(f"Could not parse date: {d_str}")

    # Accept HH:MM or HH:MM:SS
    time_fmt = "%H:%M:%S" if t_str.count(":") == 2 else "%H:%M"
    parsed_time = datetime.strptime(t_str, time_fmt).time()

    return datetime.combine(parsed_date, parsed_time)


def score_from_result(result: str) -> float:
    result = result.upper()
    if result.startswith("X/"):
        return 0.5
    guesses = int(result.split("/")[0])
    return float(7 - guesses)


def fmt_pts(x: float) -> str:
    return str(int(x)) if abs(x - round(x)) < 1e-9 else f"{x:.1f}"


def parse_double_dates(text: str):
    dates = set()
    for part in re.split(r"[,\n]+", text.strip()):
        p = part.strip()
        if not p:
            continue
        try:
            datetime.strptime(p, "%Y-%m-%d")
            dates.add(p)
        except ValueError:
            pass
    return dates


def puzzle_for_day(start_date: date, start_puzzle: int, d: date):
    return start_puzzle + (d - start_date).days


def day_for_puzzle(start_date: date, start_puzzle: int, puzzle: int):
    return start_date + timedelta(days=(puzzle - start_puzzle))


# -----------------------------
# Streamlit UI
# -----------------------------

st.set_page_config(page_title="Wordle WhatsApp League Scorer")
st.title("🧩 Wordle WhatsApp League Scorer")

with st.expander("Season settings", expanded=True):
    season_start_date = st.date_input("Season start date")
    season_weeks = st.number_input("Season length (weeks)", min_value=1, value=10)
    season_start_puzzle = st.number_input("Puzzle number on start date", min_value=1, value=1)
    report_week = st.number_input("Week to report", min_value=1, value=1)
    prefer_dmy = st.checkbox("My WhatsApp export uses DD/MM/YYYY", value=True)
    double_text = st.text_area("Double points dates (YYYY-MM-DD)", value="")
    double_dates = parse_double_dates(double_text)

uploaded = st.file_uploader("Upload WhatsApp export (.txt)", type=["txt"])

if not uploaded:
    st.stop()

raw_text = uploaded.read().decode("utf-8", errors="replace")
lines = raw_text.splitlines()

first_sub = {}
players = set()

for line in lines:
    match = None
    for pattern in LINE_PATS:
        match = pattern.match(line)
        if match:
            break

    if not match:
        continue

    try:
        dt = parse_dt(match.group("d"), match.group("t"), prefer_dmy)
    except:
        continue

    msg = match.group("msg")
    name = match.group("name").strip()

    wordle_match = WORDLE_PAT.search(msg)
    if not wordle_match:
        continue

    puzzle = int(wordle_match.group("puzzle").replace(",", ""))
    result = wordle_match.group("result")

    players.add(name)
    key = (name, puzzle)

    if key not in first_sub or dt < first_sub[key][0]:
        first_sub[key] = (dt, result)

players = sorted(players)

season_days = int(season_weeks) * 7
season_dates = [season_start_date + timedelta(days=i) for i in range(season_days)]
season_puzzles = [
    puzzle_for_day(season_start_date, int(season_start_puzzle), d)
    for d in season_dates
]

week_start = season_start_date + timedelta(days=(int(report_week) - 1) * 7)
week_dates = [week_start + timedelta(days=i) for i in range(7)]
week_puzzles = [
    puzzle_for_day(season_start_date, int(season_start_puzzle), d)
    for d in week_dates
]

def multiplier(puzzle):
    d = day_for_puzzle(season_start_date, int(season_start_puzzle), puzzle)
    return 2 if d.isoformat() in double_dates else 1

week_points = defaultdict(float)
season_points = defaultdict(float)
missing = defaultdict(list)

for puzzle in season_puzzles:
    mult = multiplier(puzzle)
    for pl in players:
        res = first_sub.get((pl, puzzle))
        if res:
            season_points[pl] += score_from_result(res[1]) * mult

for puzzle in week_puzzles:
    mult = multiplier(puzzle)
    for pl in players:
        res = first_sub.get((pl, puzzle))
        if res:
            week_points[pl] += score_from_result(res[1]) * mult
        else:
            missing[pl].append(puzzle)

week_ranked = sorted(players, key=lambda p: (-week_points[p], p))
season_ranked = sorted(players, key=lambda p: (-season_points[p], p))

output = []
output.append(f"🏁 Wordle League — Week {report_week}")
output.append("")
output.append("📊 Weekly points")
for i, p in enumerate(week_ranked, 1):
    output.append(f"{i}. {p}: {fmt_pts(week_points[p])}")

output.append("")
output.append("🏆 Season total")
for i, p in enumerate(season_ranked, 1):
    output.append(f"{i}. {p}: {fmt_pts(season_points[p])}")

output.append("")
output.append("❗ Missing submissions (0 points)")
for p in players:
    if missing[p]:
        output.append(f"- {p}: {', '.join(map(str, missing[p]))}")

st.text_area("Copy into WhatsApp", "\n".join(output), height=400)
