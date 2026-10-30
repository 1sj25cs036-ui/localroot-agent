"""Small wrapper around the Qloo API.

NOTE: written from Qloo's public Insights API shape (X-Api-Key header,
/search and /v2/insights). If the hackathon docs show a different base URL
or parameter name, change it in ONE place: the constants below.
"""
import requests

DEFAULT_BASE_URL = "https://hackathon.api.qloo.com"

# Which Qloo entity type to search for each taste category in the app.
TYPE_URNS = {
    "films": "urn:entity:movie",
    "music": "urn:entity:artist",
    "design": "urn:entity:brand",
}


class QlooError(Exception):
    pass


class QlooClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, timeout: int = 20):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"X-Api-Key": api_key, "Accept": "application/json"})

    def _get(self, path: str, params: dict) -> dict:
        try:
            r = self.session.get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        except requests.RequestException as e:
            raise QlooError(f"Could not reach Qloo: {e}") from e
        if r.status_code != 200:
            raise QlooError(f"Qloo returned {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except ValueError as e:
            raise QlooError("Qloo returned something that is not JSON") from e

    @staticmethod
    def _results(data: dict) -> list:
        if isinstance(data.get("results"), list):
            return data["results"]
        inner = data.get("results")
        if isinstance(inner, dict):
            for key in ("entities", "results"):
                if isinstance(inner.get(key), list):
                    return inner[key]
        if isinstance(data.get("data"), dict) and isinstance(data["data"].get("results"), list):
            return data["data"]["results"]
        return []

    def match_taste(self, name: str, category: str) -> dict | None:
        """Find the best Qloo entity for one favorite thing."""
        data = self._get(
            "/search",
            {"query": name, "types": TYPE_URNS.get(category, ""), "take": 1},
        )
        results = self._results(data)
        if not results:
            return None
        e = results[0]
        tags = []
        for t in e.get("tags", []) or []:
            tags.append(t.get("name") if isinstance(t, dict) else str(t))
        return {
            "input": name,
            "category": category,
            "entity_id": e.get("entity_id") or e.get("id"),
            "name": e.get("name", name),
            "tags": [t for t in tags if t][:8],
        }

    def match_all(self, tastes: dict[str, list[str]]) -> tuple[list[dict], list[str]]:
        """tastes = {"films": [...], "music": [...], "design": [...]}.
        Returns (matched entities, inputs Qloo could not find)."""
        matched, missed = [], []
        for category, names in tastes.items():
            for n in names:
                m = self.match_taste(n, category)
                (matched if m and m["entity_id"] else missed).append(m or n)
        missed = [x if isinstance(x, str) else x["input"] for x in missed]
        return matched, missed

    def taste_places(self, entity_ids: list[str], neighborhood: str, take: int = 30) -> list[str]:
        """Names of places Qloo thinks fit these tastes near the neighborhood.
        Used only to give a ranking boost to matching OpenStreetMap places."""
        if not entity_ids:
            return []
        data = self._get(
            "/v2/insights",
            {
                "filter.type": "urn:entity:place",
                "signal.interests.entities": ",".join(entity_ids),
                "filter.location.query": neighborhood,
                "take": take,
            },
        )
        return [r.get("name", "") for r in self._results(data) if r.get("name")]
