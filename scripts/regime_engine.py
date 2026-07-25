#!/usr/bin/env python3
"""
Market Regime Engine — Causal K-means regime detection for Pipeline V3.
Fetches BTC daily candles from Binance, runs the jump-penalized model, writes JSON.
"""
import json, math, os, time, urllib.request
from datetime import datetime, timezone

OUTPUT = "/home/maswilee/projects/pipeline-dashboard-v3/data/market_regime.json"
LAMBDA = 4.0
TRAINING_WINDOW = 365
REFIT_EVERY = 7

def fetch_daily_klines():
    """Fetch up to 500 daily BTC candles from Binance."""
    url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=500"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def build_features(klines):
    """Build backward-looking features: log_return, momentum_20, volatility_20, drawdown."""
    rows = []
    for k in klines:
        rows.append({
            "date": datetime.fromtimestamp(k[0]/1000, tz=timezone.utc).strftime("%Y-%m-%d"),
            "close": float(k[4])
        })
    
    n = len(rows)
    for i in range(n):
        close = rows[i]["close"]
        # log return
        if i > 0:
            rows[i]["log_return"] = math.log(close / rows[i-1]["close"])
        else:
            rows[i]["log_return"] = 0.0
        
        # 20-day momentum
        if i >= 20:
            rows[i]["momentum_20"] = (close - rows[i-20]["close"]) / rows[i-20]["close"]
        else:
            rows[i]["momentum_20"] = 0.0
        
        # 20-day realized volatility (annualized)
        if i >= 20:
            log_rets = [rows[j]["log_return"] for j in range(i-19, i+1) if rows[j]["log_return"] != 0]
            if len(log_rets) > 1:
                mean = sum(log_rets) / len(log_rets)
                var = sum((r - mean)**2 for r in log_rets) / (len(log_rets) - 1)
                rows[i]["volatility_20"] = math.sqrt(var) * math.sqrt(365)
            else:
                rows[i]["volatility_20"] = 0.0
        else:
            rows[i]["volatility_20"] = 0.0
        
        # Drawdown from running peak
        peak = max(r["close"] for r in rows[:i+1])
        rows[i]["drawdown"] = (close / peak) - 1.0
    
    # Drop rows without full feature window (first 20 rows)
    return [r for r in rows if r.get("volatility_20", 0) != 0 or r.get("momentum_20") != 0]

def standardize(values):
    """Simple standardization: (x - mean) / std."""
    if len(values) < 2:
        return [0.0] * len(values)
    mean = sum(values) / len(values)
    var = sum((x - mean)**2 for x in values) / (len(values) - 1)
    std = math.sqrt(var) if var > 0 else 1.0
    return [(x - mean) / std for x in values]

def run_regime_model(features, lambda_penalty=LAMBDA, training_window=TRAINING_WINDOW, refit_every=REFIT_EVERY):
    """
    Causal K-means regime detector with switching penalty.
    
    At each step i:
    1. Fit scaler + 3-means on rows [i-training_window, i) only
    2. Compute distances to each cluster center
    3. Add lambda to clusters that differ from previous regime
    4. Pick lowest adjusted score
    5. Label clusters: lowest momentum = Bear, highest = Bull, middle = Neutral
    """
    feature_keys = ["log_return", "momentum_20", "volatility_20", "drawdown"]
    n = len(features)
    results = []
    previous_regime = None
    cluster_names = None
    centers = None
    
    start = min(training_window, max(60, n // 3))
    
    for i in range(start, n):
        # Refit K-means periodically
        should_refit = (i - start) % refit_every == 0 or cluster_names is None
        
        if should_refit:
            train_start = max(0, i - training_window)
            train_data = features[train_start:i]
            
            if len(train_data) < 60:
                continue
            
            # Standardize each feature
            train_arrays = {k: [r[k] for r in train_data] for k in feature_keys}
            train_std = {k: standardize(train_arrays[k]) for k in feature_keys}
            
            # Build standardized points
            points = [[train_std[k][j] for k in feature_keys] for j in range(len(train_data))]
            
            # K-means++ initialization
            centers = kmeans_pp(points, k=3)
            # Lloyd iterations
            for _ in range(50):
                labels = assign_clusters(points, centers)
                new_centers = recompute_centers(points, labels, 3)
                if centers_equal(centers, new_centers):
                    break
                centers = new_centers
            
            # Un-standardize centers for labeling
            train_means = {k: sum(train_arrays[k])/len(train_arrays[k]) for k in feature_keys}
            train_stds = {k: math.sqrt(sum((x-train_means[k])**2 for x in train_arrays[k])/(len(train_arrays[k])-1)) if len(train_arrays[k])>1 else 1.0 for k in feature_keys}
            
            raw_centers = []
            for c in centers:
                raw_centers.append([c[j] * train_stds[feature_keys[j]] + train_means[feature_keys[j]] for j in range(4)])
            
            # Label by momentum (index 1)
            mom_idx = 1
            momentum_vals = [c[mom_idx] for c in raw_centers]
            ordered = sorted(range(3), key=lambda x: momentum_vals[x])
            cluster_names = {ordered[0]: "Bear", ordered[1]: "Neutral", ordered[2]: "Bull"}
        
        # Classify current point
        current = features[i]
        
        # Standardize using same stats
        train_start2 = max(0, i - training_window)
        train_data2 = features[train_start2:i]
        train_arrays2 = {k: [r[k] for r in train_data2] for k in feature_keys}
        train_means2 = {k: sum(v)/len(v) if v else 0 for k, v in train_arrays2.items()}
        train_vars2 = {k: sum((x-train_means2[k])**2 for x in v)/(len(v)-1) if len(v)>1 else 1.0 for k, v in train_arrays2.items()}
        train_stds2 = {k: math.sqrt(train_vars2[k]) for k in feature_keys}
        
        current_scaled = [(current[k] - train_means2[k]) / max(train_stds2[k], 0.001) for k in feature_keys]
        
        # Distances to each cluster
        distances = [sum((current_scaled[j] - centers[c][j])**2 for j in range(4)) for c in range(3)]
        
        # Raw cluster (no penalty)
        raw_cluster = min(range(3), key=lambda c: distances[c])
        raw_regime = cluster_names[raw_cluster]
        
        # Adjusted with penalty
        adjusted = distances[:]
        if previous_regime is not None:
            for c in range(3):
                if cluster_names[c] != previous_regime:
                    adjusted[c] += lambda_penalty
        
        chosen = min(range(3), key=lambda c: adjusted[c])
        chosen_regime = cluster_names[chosen]
        switched = previous_regime is not None and chosen_regime != previous_regime
        
        results.append({
            "date": features[i]["date"],
            "close": features[i]["close"],
            "regime": chosen_regime,
            "raw_regime": raw_regime,
            "switched": switched,
            "log_return": features[i]["log_return"],
            "momentum_20": features[i]["momentum_20"],
            "volatility_20": features[i]["volatility_20"],
            "drawdown": features[i]["drawdown"],
            "distance_bear": round(distances[list(cluster_names.keys())[list(cluster_names.values()).index("Bear")]], 4) if "Bear" in cluster_names.values() else 0,
            "distance_neutral": round(distances[list(cluster_names.keys())[list(cluster_names.values()).index("Neutral")]], 4) if "Neutral" in cluster_names.values() else 0,
            "distance_bull": round(distances[list(cluster_names.keys())[list(cluster_names.values()).index("Bull")]], 4) if "Bull" in cluster_names.values() else 0,
        })
        previous_regime = chosen_regime
    
    return results

def kmeans_pp(points, k=3):
    """K-means++ initialization."""
    import random
    random.seed(42)
    centers = [points[random.randint(0, len(points)-1)]]
    for _ in range(1, k):
        dists = [min(sum((p[c] - centers[j][c])**2 for c in range(len(p))) for j in range(len(centers))) for p in points]
        total = sum(dists)
        r = random.random() * total
        cumulative = 0
        for i, d in enumerate(dists):
            cumulative += d
            if cumulative >= r:
                centers.append(points[i])
                break
    return centers

def assign_clusters(points, centers):
    return [min(range(len(centers)), key=lambda c: sum((p[j]-centers[c][j])**2 for j in range(len(p)))) for p in points]

def recompute_centers(points, labels, k):
    new_centers = []
    for c in range(k):
        cluster_points = [p for p, l in zip(points, labels) if l == c]
        if cluster_points:
            dim = len(cluster_points[0])
            new_centers.append([sum(p[j] for p in cluster_points)/len(cluster_points) for j in range(dim)])
        else:
            new_centers.append([0.0] * len(points[0]))
    return new_centers

def centers_equal(a, b):
    return all(sum((a[i][j]-b[i][j])**2 for j in range(len(a[i]))) < 0.0001 for i in range(len(a)))

def summarize(results):
    if not results:
        return {}
    switches = sum(1 for r in results if r["switched"])
    first_date = results[0]["date"]
    last_date = results[-1]["date"]
    try:
        days = max(1, (datetime.strptime(last_date, "%Y-%m-%d") - datetime.strptime(first_date, "%Y-%m-%d")).days)
    except:
        days = len(results)
    switches_per_year = round(switches / days * 365.25, 2)
    
    # Average duration
    durations = []
    current_dur = 0
    prev = None
    for r in results:
        if prev and r["regime"] != prev:
            durations.append(current_dur)
            current_dur = 0
        current_dur += 1
        prev = r["regime"]
    durations.append(current_dur)
    avg_duration = round(sum(durations) / len(durations), 1) if durations else 0
    
    return {
        "switches": switches,
        "switches_per_year": switches_per_year,
        "average_duration_days": avg_duration,
        "data_start": first_date,
        "data_end": last_date,
        "total_rows": len(results)
    }

def main():
    print("Fetching BTC daily klines (500 candles)...")
    klines = fetch_daily_klines()
    print(f"  Got {len(klines)} daily candles")
    
    print("Building features...")
    features = build_features(klines)
    print(f"  {len(features)} rows with full features")
    
    print(f"Running regime model (λ={LAMBDA})...")
    results = run_regime_model(features)
    print(f"  {len(results)} classified rows")
    
    summary = summarize(results)
    latest = results[-1] if results else None
    
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lambda": LAMBDA,
        "training_window": TRAINING_WINDOW,
        "summary": summary,
        "latest": latest,
        "regime_counts": {
            "Bull": sum(1 for r in results if r["regime"] == "Bull"),
            "Neutral": sum(1 for r in results if r["regime"] == "Neutral"),
            "Bear": sum(1 for r in results if r["regime"] == "Bear"),
        },
        "history": results[-90:]  # Last 90 days for chart
    }
    
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(output, f, indent=2)
    
    if latest:
        print(f"\n✓ Written to {OUTPUT}")
        print(f"  Current: {latest['regime']} | Price: ${latest['close']:,.0f}")
        print(f"  Switches/yr: {summary['switches_per_year']} | Avg duration: {summary['average_duration_days']} days")
        print(f"  Regime split: {output['regime_counts']}")

if __name__ == "__main__":
    main()
