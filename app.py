import re
from datetime import datetime, date, timedelta
from collections import defaultdict
import streamlit as st


# -----------------------------
# Helpers
# -----------------------------
WORDLE_PAT = re.compile(r"\bWordle\s+(?P<puzzle>\d+)\s+(?P<result>([1-6]/6|X/6))", re.IGNORECASE)

LINE_PATS = [
    # iPhone common:
    # "12/01/2026, 08:15 - Name: message"
    re.compile(r"^(?P<d>\d{1,2}/\d{1,2}/\d{2,4}), (?P<t>\d{1,2}:\d{2}) - (?P<name>.*?): (?P<msg>.*)$"),
    # Another common:
    # "[12/01/2026, 08:15] Name: message"
    re.compile(r"^\[(?P<d>\d{1,2}/\d{1,2}/\d{2,4}), (?P<t>\d{1,2}:\d{2})\] (?P<name>.*?): (?P<msg>.*)$"),
]

def parse_dt(d_str: str, t_str: str, prefer_dmy: bool) -> datetime:
    """Try to parse WhatsApp export date + time."""
    fmts = []
    if prefer_dmy:
        fmts = ["%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y", "%m/%d/%y"]
    else:
        fmts = ["%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y", "%d/%m/%y"]

    d = None
    for fmt in fmts:
        try:
            d = datetime.strptime(d_str, fmt).date()
            break
        except ValueError:
            continue
    if d is None:
        raise ValueError(f"Could not parse date: {d_str}")

    tm = datetime.strptime(t_str, "%H:%M").time()
    return datetime.combine(d, tm)

def score_from_result(result: str) -> float:
    r = result.upper()
    if r.startswith("X/"):
        return 0.5
    m = re.match(r"([1-6])/6", r)
    if not m:
        return 0.0
    guesses = int(m.group(1))
    return float(7 - guesses)  # 1->6, 2->5 ... 6->1

def fmt_pts(x: float) -> str:
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return f"{x:.1f}"

def safe_name(s: str) -> str:
    return s.strip()

def parse_double_dates(text: str):
    """Accepts dates separated by commas or newlines; returns a set of YYYY-MM-DD strings."""
    dates = set()
    for part in re.split(r"[,\n]+", text.strip()):
        p = part.strip()
        if not p:
            continue
        # basic validation
        try:
            _ = datetime.strptime(p, "%Y-%m-%d").date()
            dates.add(p)
        except ValueError:
            # ignore invalid; we will show warning elsewhere
            pass
    return dates

def week_date_range(season_start: date, week_num: int, week_start: str):
    """Return start and end date (inclusive) for a given week number."""
    # week 1 starts on season_start regardless, but we allow the UI to define what day that is.
    start = season_start + timedelta(days=(week_num - 1) * 7)
    end = start + timedelta(days=6)
    return start, end

def puzzle_for_day(season_start_date: date, season_start_puzzle: int, d: date) -> int:
    return season_start_puzzle + (d - season_start_date).days

def day_for_puzzle(season_start_date: date, season_start_puzzle: int, puzzle: int) -> date:
    return season_start_date + timedelta(days=(puzzle - season_start_puzzle))


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="Wordle WhatsApp League Scorer", page_icon="🧩")
st.title("🧩 Wordle WhatsApp League Scorer")
st.write("Upload your **WhatsApp chat export (.txt)** and get a WhatsApp-ready leaderboard.")

with st.expander("✅ One-time season settings (you can change these anytime)", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        season_start_date = st.date_input("Season start date (Week 1 Day 1)", value=date.today())
        season_weeks = st.number_input("Season length (weeks)", min_value=1, max_value=52, value=10, step=1)
    with col2:
        season_start_puzzle = st.number_input("Wordle puzzle number on the start date", min_value=1, value=1, step=1)
        report_week = st.number_input("Week to report", min_value=1, max_value=int(season_weeks), value=1, step=1)

    st.caption("Tip: choose your Week 1 start date and the Wordle puzzle number for that day. The app maps every date → puzzle number.")

    prefer_dmy = st.checkbox("My WhatsApp export uses day/month format (DD/MM/YYYY)", value=True)

    double_text = st.text_area(
        "Double points dates (YYYY-MM-DD), separated by commas or new lines",
        value="",
        height=100,
        placeholder="e.g.\n2026-02-11\n2026-03-04"
    )
    double_dates = parse_double_dates(double_text)

    # Quick validation feedback for entered dates
    invalid_parts = []
    for part in re.split(r"[,\n]+", double_text.strip()):
        p = part.strip()
        if not p:
            continue
        try:
            datetime.strptime(p, "%Y-%m-%d").date()
        except ValueError:
            invalid_parts.append(p)
    if invalid_parts:
        st.warning("These double-point dates look invalid (should be YYYY-MM-DD): " + ", ".join(invalid_parts))

uploaded = st.file_uploader("Upload WhatsApp export (.txt)", type=["txt"])

if not uploaded:
    st.info("Export your WhatsApp group chat **Without Media**, then upload the .txt file here.")
    st.stop()

raw_text = uploaded.read().decode("utf-8", errors="replace")
lines = raw_text.splitlines()

# Parse first submissions only
first_sub = {}  # (name, puzzle) -> (timestamp, result)
all_players = set()

for line in lines:
    m = None
    for lp in LINE_PATS:
        m = lp.match(line)
        if m:
            break
    if not m:
        continue

    name = safe_name(m.group("name"))
    msg = m.group("msg").strip()
    try:
        dt = parse_dt(m.group("d"), m.group("t"), prefer_dmy=prefer_dmy)
    except ValueError:
        continue

    wm = WORDLE_PAT.search(msg)
    if not wm:
        continue

    puzzle = int(wm.group("puzzle"))
    result = wm.group("result").upper()

    all_players.add(name)
    key = (name, puzzle)

    # first submission only -> keep earliest timestamp
    if key not in first_sub or dt < first_sub[key][0]:
        first_sub[key] = (dt, result)

players = sorted(all_players, key=lambda s: s.lower())

# Build season + report week ranges
season_days = int(season_weeks) * 7
season_dates = [season_start_date + timedelta(days=i) for i in range(season_days)]
season_puzzles = [puzzle_for_day(season_start_date, int(season_start_puzzle), d) for d in season_dates]

w_start, w_end = week_date_range(season_start_date, int(report_week), week_start="Mon")
week_dates = [w_start + timedelta(days=i) for i in range(7)]
week_puzzles = [puzzle_for_day(season_start_date, int(season_start_puzzle), d) for d in week_dates]

def multiplier_for_puzzle(puz: int) -> float:
    d = day_for_puzzle(season_start_date, int(season_start_puzzle), puz)
    return 2.0 if d.isoformat() in double_dates else 1.0

# Score
week_points = defaultdict(float)
season_points = defaultdict(float)
missing_week = defaultdict(list)

for puz in season_puzzles:
    mult = multiplier_for_puzzle(puz)
    for pl in players:
        res = first_sub.get((pl, puz))
        pts = score_from_result(res[1]) * mult if res else 0.0
        season_points[pl] += pts

for d, puz in zip(week_dates, week_puzzles):
    mult = multiplier_for_puzzle(puz)
    for pl in players:
        res = first_sub.get((pl, puz))
        if res:
            week_points[pl] += score_from_result(res[1]) * mult
        else:
            missing_week[pl].append(puz)

week_ranked = sorted(players, key=lambda pl: (-week_points[pl], pl.lower()))
season_ranked = sorted(players, key=lambda pl: (-season_points[pl], pl.lower()))

double_days_in_week = [d.isoformat() for d in week_dates if d.isoformat() in double_dates]

# Output block
out = []
out.append(f"🏁 Wordle League — Week {int(report_week)} ({w_start.isoformat()} to {w_end.isoformat()})")
if double_days_in_week:
    out.append("🎂 Double points days this week: " + ", ".join(double_days_in_week))
out.append("")
out.append("📊 Weekly points")
for i, pl in enumerate(week_ranked, 1):
    out.append(f"{i}. {pl}: {fmt_pts(week_points[pl])}")
out.append("")
out.append(f"🏆 Season total (Weeks 1–{int(report_week)})")
for i, pl in enumerate(season_ranked, 1):
    out.append(f"{i}. {pl}: {fmt_pts(season_points[pl])}")
out.append("")
out.append("❗ Missing submissions this week (0 points)")
any_missing = False
for pl in players:
    if missing_week[pl]:
        any_missing = True
        out.append(f"- {pl}: " + ", ".join(str(p) for p in missing_week[pl]))
if not any_missing:
    out.append("None 🎉")

st.subheader("✅ Copy/paste this into WhatsApp")
st.text_area("Leaderboard (WhatsApp-ready)", value="\n".join(out), height=350)

st.caption("Rules: first submission only; late submissions allowed; X/6 scores 0.5; double dates score x2.")
