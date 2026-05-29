"""
ml/shot_quality/evaluate.py

Error analysis for the shot quality models.

The goal here is not just to report accuracy — it's to understand
WHERE the model fails and WHY. This is what makes an ML project
credible. A model you can't critique is a model you don't understand.

Analysis sections:
  1. Performance by zone — does the model struggle in specific areas?
  2. Performance by distance bucket — does accuracy degrade at range?
  3. Calibration — when the model says 60%, does it go in 60% of the time?
  4. Feature importance — what does XGBoost actually care about?
  5. Expected points vs actual — the metric we actually care about
"""

import os
import pickle
import numpy as np
import pandas as pd
from sklearn.metrics import log_loss, brier_score_loss
from data import load_shots, get_features_and_label, get_train_test_split

MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")


def load_model(filename):
    path = os.path.join(MODEL_DIR, filename)
    with open(path, "rb") as f:
        return pickle.load(f)


def section(title):
    print(f"\n── {title} {'─' * (50 - len(title))}")


# ── 1. Performance by zone ─────────────────────────────────────────────────────

def error_by_zone(model, X_test, y_test, df_test):
    section("Model accuracy by zone (XGBoost)")
    y_proba = model.predict_proba(X_test)[:, 1]

    # Reconstruct zone from one-hot columns
    zone_cols = [c for c in X_test.columns if c.startswith("shot_zone_basic_")]
    zone_names = [c.replace("shot_zone_basic_", "") for c in zone_cols]

    results = []
    for col, zone in zip(zone_cols, zone_names):
        mask = X_test[col] == 1
        if mask.sum() < 100:
            continue
        actual_pct   = y_test[mask].mean()
        predicted_pct = y_proba[mask].mean()
        count        = mask.sum()
        results.append((zone, count, actual_pct, predicted_pct))

    print(f"{'Zone':<30} {'Count':>8} {'Actual%':>9} {'Predicted%':>11} {'Error':>7}")
    print("-" * 70)
    for zone, count, actual, predicted in sorted(results, key=lambda x: -x[1]):
        error = predicted - actual
        print(f"{zone:<30} {count:>8,} {actual*100:>8.1f}% {predicted*100:>10.1f}% {error*100:>+6.1f}%")


# ── 2. Performance by distance bucket ─────────────────────────────────────────

def error_by_distance(model, X_test, y_test):
    section("Model accuracy by distance (XGBoost)")
    y_proba = model.predict_proba(X_test)[:, 1]

    bins   = [0, 5, 10, 15, 20, 25, 30, 100]
    labels = ["0-5ft", "6-10ft", "11-15ft", "16-20ft", "21-25ft", "26-30ft", "30ft+"]

    distances = X_test["shot_distance"]
    buckets   = pd.cut(distances, bins=bins, labels=labels)

    print(f"{'Range':<12} {'Count':>8} {'Actual%':>9} {'Predicted%':>11} {'Error':>7}")
    print("-" * 55)
    for label in labels:
        mask = buckets == label
        if mask.sum() < 100:
            continue
        actual    = y_test[mask].mean()
        predicted = y_proba[mask].mean()
        error     = predicted - actual
        print(f"{label:<12} {mask.sum():>8,} {actual*100:>8.1f}% {predicted*100:>10.1f}% {error*100:>+6.1f}%")


# ── 3. Calibration ─────────────────────────────────────────────────────────────

def calibration_check(model, X_test, y_test, name):
    section(f"Calibration — {name}")
    print("When the model predicts X%, does the shot go in X% of the time?")
    print()
    y_proba = model.predict_proba(X_test)[:, 1]

    bins   = [0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0]
    labels = ["<20%", "20-30%", "30-40%", "40-50%", "50-60%", "60-70%", "70-80%", "80%+"]

    buckets = pd.cut(y_proba, bins=bins, labels=labels)

    print(f"{'Predicted':>12} {'Count':>8} {'Actual%':>9}  {'Calibrated?'}")
    print("-" * 50)
    for label in labels:
        mask = buckets == label
        if mask.sum() < 100:
            continue
        actual = y_test[mask].mean() * 100
        mid    = (bins[labels.index(label)] + bins[labels.index(label)+1]) / 2 * 100
        diff   = actual - mid
        status = "✓ good" if abs(diff) < 5 else "⚠ off"
        print(f"{label:>12} {mask.sum():>8,} {actual:>8.1f}%  {status} (off by {diff:+.1f}%)")


# ── 4. Feature importance (XGBoost only) ──────────────────────────────────────

def feature_importance(xgb_model, feature_names):
    section("Feature importance (XGBoost)")
    print("How much does each feature contribute to predictions?")
    print()
    importances = xgb_model.feature_importances_
    pairs = sorted(zip(feature_names, importances), key=lambda x: -x[1])

    for feature, importance in pairs:
        bar = "█" * int(importance * 200)
        print(f"{feature:<45} {importance:.4f}  {bar}")


# ── 5. Expected points vs actual ──────────────────────────────────────────────

def expected_vs_actual(xgb_model, X_test, y_test):
    section("Expected points vs actual points by zone")
    print("xPTS = predicted FG% × point value (2 or 3)")
    print()
    y_proba = xgb_model.predict_proba(X_test)[:, 1]
    is_3pt  = X_test["shot_type_3PT"].values

    xpts   = y_proba * (np.where(is_3pt, 3, 2))
    actual = y_test.values * (np.where(is_3pt, 3, 2))

    zone_cols  = [c for c in X_test.columns if c.startswith("shot_zone_basic_")]
    zone_names = [c.replace("shot_zone_basic_", "") for c in zone_cols]

    print(f"{'Zone':<30} {'Count':>8} {'xPTS':>7} {'Actual PTS':>11}")
    print("-" * 60)
    results = []
    for col, zone in zip(zone_cols, zone_names):
        mask = X_test[col].values == 1
        if mask.sum() < 100:
            continue
        results.append((zone, mask.sum(), xpts[mask].mean(), actual[mask].mean()))

    for zone, count, xp, ap in sorted(results, key=lambda x: -x[3]):
        print(f"{zone:<30} {count:>8,} {xp:>7.3f} {ap:>11.3f}")


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Loading data and models...")
    X_train, X_test, y_train, y_test = get_train_test_split()

    lr_model  = load_model("logistic_regression.pkl")
    xgb_model = load_model("xgboost.pkl")

    error_by_zone(xgb_model, X_test, y_test, None)
    error_by_distance(xgb_model, X_test, y_test)
    calibration_check(lr_model,  X_test, y_test, "Logistic Regression")
    calibration_check(xgb_model, X_test, y_test, "XGBoost")
    feature_importance(xgb_model, X_test.columns.tolist())
    expected_vs_actual(xgb_model, X_test, y_test)
