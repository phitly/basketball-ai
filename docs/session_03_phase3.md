# Session 03 — Phase 3: Shot Quality ML Model

**Date:** May 29, 2026
**Goal:** Train a model that predicts the probability any shot goes in, giving us expected points per shot attempt — a richer metric than raw FG%.

---

## The Core Idea

You have 2 million shots in your database. Each shot has attributes — distance, zone, shot type, game clock. You also know whether each shot went in (made = True/False).

Machine learning here means: learn the relationship between those attributes and whether the shot was made, so you can apply it to any new shot and get a probability.

That probability is called **xFG% (expected field goal percentage)**. Multiply by point value (2 or 3) and you get **expected points per shot (xPTS)**.

Why does this matter? A 28-foot contested three and a layup both count as "one shot attempt" in a box score. This model treats them very differently.

---

## Files Built

```
ml/shot_quality/
├── data.py      — pulls shots from DB, cleans, encodes, splits train/test
├── train.py     — trains logistic regression + XGBoost, saves models
├── evaluate.py  — error analysis: by zone, distance, calibration, feature importance
└── models/
    ├── logistic_regression.pkl
    └── xgboost.pkl
```

---

## Part 1 — Data Preparation (data.py)

### What the data looks like
Each row from the shots table:
```
(12, 'In The Paint (Non-RA)', '2PT', True,  1, '11:00')
(20, 'Mid-Range',             '2PT', False, 1, '10:27')
(1,  'Restricted Area',       '2PT', False, 1, '09:12')
```

### Key transforms applied
- **Drop backcourt shots** — 2.3% FG%, pure noise
- **Drop null zones/distances** — 367 rows with missing zone
- **game_clock "MM:SS" → seconds** — models need numbers, not strings
- **One-hot encoding** — "Restricted Area" becomes a column with 1/0
- **Train/test split** — 80% train, 20% test, random_state=42 for reproducibility

### Final dataset
- Training: 1,603,173 shots
- Test: 400,794 shots
- Features: 11 (distance, period, seconds_remaining, 6 zone columns, 2 shot type columns)
- Made% in train: 46.4% — Made% in test: 46.2% (balanced split)

---

## Part 2 — Two Models (train.py)

### Why two models?

**Logistic Regression** finds straight-line relationships between features and outcome. Fast, interpretable, gives a baseline. Uses StandardScaler — without it, large-number features (seconds_remaining: 0-720) would overpower small ones (period: 1-4).

**XGBoost** learns non-linear patterns through gradient boosted decision trees. Trees split on thresholds, so scaling isn't needed. Slower to train, more powerful.

Comparing both tells us whether the added complexity is worth it.

### Results

| Metric | Logistic Regression | XGBoost | Baseline |
|---|---|---|---|
| Accuracy | 62.2% | 62.6% | 54% |
| Log Loss | 0.661 | 0.653 | 0.690 |
| Brier Score | 0.234 | 0.231 | 0.249 |

- Both models beat the baseline — they're actually learning something
- XGBoost wins on every metric
- 62% accuracy sounds low but basketball shots are genuinely hard to predict — this is meaningful signal

---

## Part 3 — Error Analysis (evaluate.py)

### By zone
All zones within 0.3% of actual — no systematic failures anywhere.

### By distance
All distance buckets within 0.6% — errors are noise, not bias.

### Calibration
XGBoost is well-calibrated across the full probability range (12% to 80%+). When it predicts 70-80%, shots actually go in 75.6% of the time. Logistic regression only spreads predictions into 4 buckets — much less useful.

### Feature importance (XGBoost)
| Feature | Importance |
|---|---|
| shot_zone_basic_Restricted Area | 84% |
| shot_distance | 12% |
| shot_zone_basic_Above the Break 3 | 3% |
| Everything else | <1% |

**Key finding:** The model has essentially learned "is it a restricted area shot or not?" Zone dominates distance. Game clock and period barely matter. This is honest — worth documenting as a known simplification.

### Expected points vs actual (the metric we care about)
| Zone | xPTS | Actual PTS |
|---|---|---|
| Restricted Area | 1.271 | 1.274 |
| Corner 3 | ~1.158 | ~1.162 |
| Above the Break 3 | 1.060 | 1.050 |
| In Paint (Non-RA) | 0.840 | 0.840 |
| Mid-Range | 0.815 | 0.810 |

Model is accurate to within 0.01 expected points per shot in every zone.

---

## Key Concepts Introduced

**One-hot encoding** — converting text categories to numbers. "Restricted Area" becomes a 1 in the `shot_zone_basic_Restricted Area` column and 0 everywhere else. Models can't read strings, only numbers.

**Train/test split** — the model learns from train, we measure it on test. Testing on training data just checks if the model memorized the data, not whether it learned anything useful.

**StandardScaler** — normalizes features to mean=0, std=1 before logistic regression. Prevents large-scale features from dominating. Not needed for XGBoost (tree-based, threshold splits).

**Pipeline** — wraps scaler + model so scaling is always applied consistently during training and prediction.

**Calibration** — when the model says 60%, does the shot go in 60% of the time? A well-calibrated model is trustworthy for decision support, not just ranking.

**Baseline comparison** — always compare against "what if I just predicted the average?" If your model barely beats that, it's not learning anything useful.

---

## Known Limitations (Honest Assessment)

- **Zone dominates** — 84% of XGBoost's decisions come from whether it's a restricted area shot. The model is mostly a zone classifier with distance as a secondary signal.
- **No defender proximity** — defender_distance is null for most of the dataset (only available for some seasons via SportVU tracking). A contested layup and an open layup look the same to this model.
- **No player identity** — Steph Curry's 30-footer and a bench player's 30-footer are treated identically. Player skill is not in the model.
- **No context** — late-game pressure, score margin, opponent quality — all missing.

These are not bugs. They're documented limitations. Adding defender distance (Phase 3+) would be the highest-value improvement.

---

## Commands Reference

```bash
# Activate environment
source venv/Scripts/activate

# Run data check
python ml/shot_quality/data.py

# Train both models (~2 minutes)
python ml/shot_quality/train.py

# Full error analysis
python ml/shot_quality/evaluate.py
```

---

## What's Next (Phase 4)

Build the NLP Narrative Engine — auto-generate plain-English game summaries from the structured analytics output.

The key design principle: the LLM does NOT do the analysis. The metrics engine (Phase 2) and shot quality model (Phase 3) do the analysis. The LLM translates structured data into language.

Start a new chat for Phase 4.
