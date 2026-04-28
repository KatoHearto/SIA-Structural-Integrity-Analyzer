import json
import os
import random
import requests


def read_cli_payload():
    raw = input("payload")
    return json.loads(raw)


def fetch_profile(user_id):
    if not user_id:
        raise ValueError("user_id")
    token = os.getenv("API_TOKEN")
    return requests.get(f"https://example.test/users/{user_id}", headers={"Authorization": token}, timeout=5)


class StateWriter:
    def write_state(self, path, payload):
        if not path:
            raise ValueError("path")
        self.last_path = path
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"payload": payload, "nonce": random.randint(1, 9)}))
        return path
