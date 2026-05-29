"""
ml/shot_quality/train.py

Trains two models on shot data and saves them to disk:
  1. Logistic Regression — simple baseline
  2. XGBoost — captures non-linear patterns

Why two models?
  Logistic regression finds straight-line relationships between features
  and outcome. XGBoost learns non-linear patterns (e.g. distance matters
  more when the defender is close). Comparing both tells us whether the
  added complexity is worth it.

Why save models to disk?
  So the API can load them later without retraining every time.
  Training is slow — serving predictions should be instant.
"""

import os
import pickle
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import log_loss, brier_score_loss
from xgboost import XGBClassifier

from data import get_train_test_split

# Where to save trained models
MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")


def train_logistic_regression(X_train, y_train):
    """
    Train a logistic regression model.

    Why StandardScaler?
    Logistic regression is sensitive to feature scale. shot_distance ranges
    from 0-35 feet; seconds_remaining ranges from 0-720. Without scaling,
    the model overweights large-number features. StandardScaler normalizes
    everything to mean=0, std=1 before training.

    We wrap both steps in a Pipeline so scaling is always applied
    consistently — both during training and when making predictions.
    """
    print("Training Logistic Regression...")
    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("model", LogisticRegression(max_iter=1000, random_state=42)),
    ])
    pipeline.fit(X_train, y_train)
    print("  Done.")
    return pipeline


def train_xgboost(X_train, y_train):
    """
    Train an XGBoost gradient boosting model.

    Why no scaler?
    XGBoost uses decision trees internally. Trees split on thresholds,
    so the absolute scale of features doesn't affect them. No scaling needed.

    Key parameters:
      n_estimators=300  — number of trees to build (more = better, slower)
      max_depth=4       — how deep each tree can go (deeper = more complex)
      learning_rate=0.1 — how much each tree corrects the previous ones
      subsample=0.8     — use 80% of data per tree (reduces overfitting)
      eval_metric='logloss' — optimize for probability calibration
    """
    print("Training XGBoost...")
    model = XGBClassifier(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric="logloss",
        random_state=42,
        verbosity=0,
    )
    model.fit(X_train, y_train)
    print("  Done.")
    return model


def evaluate(name, model, X_test, y_test):
    """
    Print key evaluation metrics for one model.

    Metrics explained:
      Accuracy    — % of shots correctly predicted as made/missed
                    (least useful — a model guessing 'missed' every time gets 54%)
      Log Loss    — how confident and correct the probabilities are
                    (lower is better; 0 is perfect)
      Brier Score — mean squared error of probabilities
                    (lower is better; 0 is perfect)
    """
    y_pred_proba = model.predict_proba(X_test)[:, 1]
    y_pred = (y_pred_proba >= 0.5).astype(int)

    accuracy = (y_pred == y_test).mean()
    ll = log_loss(y_test, y_pred_proba)
    brier = brier_score_loss(y_test, y_pred_proba)

    print(f"\n{name}:")
    print(f"  Accuracy:    {accuracy:.4f}")
    print(f"  Log Loss:    {ll:.4f}  (lower is better)")
    print(f"  Brier Score: {brier:.4f}  (lower is better)")

    return y_pred_proba


def save_model(model, filename):
    """Save a trained model to disk using pickle."""
    os.makedirs(MODEL_DIR, exist_ok=True)
    path = os.path.join(MODEL_DIR, filename)
    with open(path, "wb") as f:
        pickle.dump(model, f)
    print(f"  Saved to {path}")


if __name__ == "__main__":
    print("Loading data...")
    X_train, X_test, y_train, y_test = get_train_test_split()

    # Train both models
    lr_model  = train_logistic_regression(X_train, y_train)
    xgb_model = train_xgboost(X_train, y_train)

    # Evaluate both
    print("\n── Evaluation ─────────────────────────────")
    lr_proba  = evaluate("Logistic Regression", lr_model,  X_test, y_test)
    xgb_proba = evaluate("XGBoost",             xgb_model, X_test, y_test)

    # Baseline: what if we just predicted the average FG% for every shot?
    baseline_proba = np.full(len(y_test), y_train.mean())
    print(f"\nBaseline (always predict avg FG%):")
    print(f"  Log Loss:    {log_loss(y_test, baseline_proba):.4f}")
    print(f"  Brier Score: {brier_score_loss(y_test, baseline_proba):.4f}")

    # Save models
    print("\n── Saving models ──────────────────────────")
    save_model(lr_model,  "logistic_regression.pkl")
    save_model(xgb_model, "xgboost.pkl")

    print("\nDone. Run evaluate.py for full error analysis.")
