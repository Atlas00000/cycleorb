"""Scorecards: one JSON per recipe in var/scorecards/, plus latest.json and index.json for the agent."""
import json
import os
from datetime import datetime

from corb.paths import VAR

DIR = os.path.join(VAR, "scorecards")


def write(recipe, verdict, payload):
    os.makedirs(DIR, exist_ok=True)
    card = dict(recipe=recipe, verdict=verdict, created_at=datetime.now().isoformat(timespec="seconds"))
    card.update({k: v for k, v in payload.items() if k not in card})
    path = os.path.join(DIR, recipe + ".json")
    for target in (path, os.path.join(DIR, "latest.json")):
        with open(target, "w", encoding="utf-8") as f:
            json.dump(card, f, indent=1)
    index_path = os.path.join(DIR, "index.json")
    index = {}
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as f:
            index = json.load(f)
    index[recipe] = dict(file=recipe + ".json", verdict=verdict, created_at=card["created_at"])
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(index.items())), f, indent=1)
    return path
