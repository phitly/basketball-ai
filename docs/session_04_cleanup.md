# Session 04 — Pre-Phase 4 Cleanup

**Date:** May 29, 2026
**Goal:** Fill known gaps before Phase 4 — populate the lineups table, write the README, and verify all endpoints against real data.

---

## What We Did

### 1. README

Created `README.md` covering:
- What the project does (with a real example from the 2024 Finals)
- Full architecture diagram
- Database row counts
- All API endpoints
- Shot quality model results table
- Local setup instructions
- Phase status tracker
- Design decisions (LLM for translation not analysis, possession-level not box score, honest ML)

### 2. Lineups Table — derive_lineups.py

Built `data_pipeline/derive_lineups.py` to populate the lineups table from play-by-play substitution events.

**How it works:**
1. Infer starting lineup for each period — collect first unique player IDs per team from period events
2. Track substitutions: `player1_id` = player going OUT (stored directly), incoming player parsed from description ("SUB: X FOR Y")
3. Build name→ID lookup scoped to each team in each game (avoids cross-team conflicts)
4. Record each lineup stint with points_for/points_against from running score columns
5. Close stints at each substitution and at end of each period

**Key discovery:** In PlayByPlayV3 substitution events, `player1_id` = the player going OUT, not coming in. The incoming player is only in the description text.

**Bugs found and fixed during development:**

*Bug 1: All lineup stints showed 0 points*
Substitution events have null home_score/away_score. `(h_score or 0)` defaulted to 0 instead of the last real score. Fix: built a `score_at_event` dict by scanning all period events and tracking the last non-null score.

*Bug 2: Scores still wrong across period boundaries*
`score_at_event` reset to (0,0) at start of each period. Q2 subs before any Q2 scoring event got wrong score. Fix: initialized `running_score` from the last score of the previous period.

*Bug 3: Starting lineup only found 4 players*
`max_events=30` was too low — the 5th starter hadn't appeared in the first 30 events. `close_lineup` required exactly 5 players, so all Q1 stints were silently dropped. Fix: increased max_events to 200, relaxed the requirement to `>= 1` player.

*Bug 4: Duplicate player IDs in lineup arrays*
Quick consecutive substitutions could add a player who was already in the lineup. Fix: check `if player_in not in new_lineup` before appending.

**Result:** 582,927 lineup stints, average 51 per game, 0 failed games. Scoring verified exact (106-88 for Finals Game 5).

**Known limitations:**
- Some stints have 4 players instead of 5 (starter inference missed one player)
- `possessions_on` = 0 for all stints (not yet computed)
- `time_on_seconds` = 0 (game clock conversion not implemented)
- `ortg/drtg/net_rtg` = null (depends on possessions_on)

### 3. Bugs Fixed in Phase 2 Endpoints

During testing these were caught and fixed:
- `get_shot_points()` in derive_possessions.py was reading cumulative player totals from PlayByPlayV3 descriptions — fixed to check `'3PT' in description`
- shots table only had made shots — fixed by adding `context_measure_simple='FGA'` to ShotChartDetail call, re-ingested (929K → 2M shots)
- Momentum endpoint home/away labels swapped — fixed by passing `home_team_id` to `build_momentum_windows()`
- Player efficiency endpoint used wrong event_type casing ("FREE_THROW" vs "Free Throw")
- FT made detection used event_subtype (doesn't contain made/missed) — fixed to check `description.notlike("MISS%")`

---

## Database State After This Session

| Table | Rows |
|---|---|
| teams | 30 |
| players | 5,103 |
| games | 11,499 |
| play_events | 5,614,774 |
| shots | 2,008,598 |
| possessions | 1,955,234 |
| lineups | 582,927 |

---

## Commands Reference

```bash
# Populate lineups table (checkpointed, safe to restart)
python data_pipeline/derive_lineups.py

# Clear and re-derive if needed
python -c "
import os, psycopg2
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(host=os.getenv('DB_HOST'), port=os.getenv('DB_PORT'), dbname=os.getenv('DB_NAME'), user=os.getenv('DB_USER'), password=os.getenv('DB_PASSWORD'))
cur = conn.cursor()
cur.execute('TRUNCATE TABLE lineups')
conn.commit()
conn.close()
"
python data_pipeline/derive_lineups.py
```

---

## What's Next (Phase 4)

Build the NLP Narrative Engine — auto-generate plain-English game summaries from the structured analytics output (possession efficiency, momentum, lineup plus/minus, shot quality).

Key design principle: the LLM does NOT do the analysis. The metrics engine computes the numbers. The LLM translates structured data into language. Every output is verifiable.

Start a new chat for Phase 4.
