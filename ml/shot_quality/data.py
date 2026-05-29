"""
ml/shot_quality/data.py

Pulls shot data from PostgreSQL, cleans it, and prepares it for the model.

What this file does:
  1. Loads all shots from the DB
  2. Drops rows with missing values
  3. Converts text columns to numbers (one-hot encoding)
  4. Converts game_clock "MM:SS" → seconds remaining
  5. Splits into train and test sets

Why a separate data.py?
  Keeps data prep logic in one place. If the DB schema changes,
  you fix it here and both models benefit automatically.
"""

import os
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sklearn.model_selection import train_test_split

load_dotenv()


def get_engine():
    url = (
        f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    )
    return create_engine(url)


def clock_to_seconds(clock_str):
    """
    Convert "MM:SS" game clock to seconds remaining in the period.
    e.g. "11:30" → 690 seconds remaining
    Returns 0 if the format is unexpected.
    """
    try:
        parts = str(clock_str).split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return 0


def load_shots():
    """
    Pull all shots from the DB and return a cleaned DataFrame.

    Columns returned:
      shot_distance    — feet from basket (integer)
      shot_zone_basic  — zone name (will be encoded)
      shot_type        — '2PT' or '3PT' (will be encoded)
      period           — 1-4 (or 5+ for OT)
      seconds_remaining — game clock converted to seconds
      made             — True/False (this is our label)
    """
    engine = get_engine()

    query = """
        SELECT
            shot_distance,
            shot_zone_basic,
            shot_type,
            period,
            game_clock,
            made
        FROM shots
        WHERE shot_zone_basic != 'nan'
          AND shot_distance IS NOT NULL
          AND game_clock IS NOT NULL
    """

    df = pd.read_sql(query, engine)
    engine.dispose()

    # Convert game clock to seconds
    df["seconds_remaining"] = df["game_clock"].apply(clock_to_seconds)
    df = df.drop(columns=["game_clock"])

    # Cap period at 4 — treat all OT periods the same
    df["period"] = df["period"].clip(upper=4)

    # Drop the small backcourt shot category — 2.3% FG%, not useful signal
    df = df[df["shot_zone_basic"] != "Backcourt"]

    # One-hot encode zone and shot type
    # e.g. "Restricted Area" becomes a column with 1/0
    df = pd.get_dummies(df, columns=["shot_zone_basic", "shot_type"], drop_first=False)

    # Convert made (True/False) to integer (1/0)
    df["made"] = df["made"].astype(int)

    return df


def get_features_and_label(df):
    """Split DataFrame into features (X) and label (y)."""
    X = df.drop(columns=["made"])
    y = df["made"]
    return X, y


def get_train_test_split(test_size=0.2, random_state=42):
    """
    Load, clean, and split data into train and test sets.

    test_size=0.2 means 20% of shots are held out for evaluation.
    random_state=42 makes the split reproducible — same split every run.

    Returns: X_train, X_test, y_train, y_test
    """
    df = load_shots()
    X, y = get_features_and_label(df)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=test_size,
        random_state=random_state,
    )

    print(f"Training samples: {len(X_train):,}")
    print(f"Test samples:     {len(X_test):,}")
    print(f"Features:         {list(X.columns)}")

    return X_train, X_test, y_train, y_test


if __name__ == "__main__":
    # Run this file directly to verify data loading works
    X_train, X_test, y_train, y_test = get_train_test_split()
    print(f"\nMade% in train: {y_train.mean():.3f}")
    print(f"Made% in test:  {y_test.mean():.3f}")
