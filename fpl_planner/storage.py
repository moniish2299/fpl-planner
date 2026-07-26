import json
import os

from fpl_planner.config import DATA_DIR


def save_json(name, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, f"{name}.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return path


def load_json(name):
    path = os.path.join(DATA_DIR, f"{name}.json")
    with open(path) as f:
        return json.load(f)
