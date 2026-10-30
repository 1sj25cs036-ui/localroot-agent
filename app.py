"""LocalRoot: taste-driven local discovery (Qloo + OpenStreetMap + Gemini)."""
import json
import math

import requests
import streamlit as st

from qloo_client import QlooClient, QlooError, DEFAULT_BASE_URL

st.set_page_config(page_title="LocalRoot", page_icon="🌱", layout="centered")

USER_AGENT = "LocalRoot-Hackathon/1.0 (streamlit demo app)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
GEMINI_MODEL_DEFAULT = "gemini-2.5-flash"
WALK_M_PER_MIN = 80  # average walking speed


# ---------- OpenStreetMap ----------
@st.cache_data(show_spinner=False, ttl=3600)
def geocode(neighborhood: str):
    r = requests.get(
        NOMINATIM_URL,
        params={"q": neighborhood, "format": "json", "limit": 1},
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"]), data[0].get("display_name", neighborhood)


CATEGORY_LABELS = {
    "cafe": "Cafe",
    "bookstore": "Bookstore",
    "music": "Music shop",
    "vintage": "Vintage shop",
}


def classify(tags: dict):
    if tags.get("amenity") == "cafe":
        return "cafe"
    shop = tags.get("shop")
    if shop == "books":
        return "bookstore"
    if shop in ("music", "records", "musical_instrument"):
        return "music"
    if shop in ("second_hand", "antiques") or (
        shop == "clothes" and tags.get("second_hand") in ("yes", "only")
    ) or "vintage" in (tags.get("name", "") + tags.get("description", "")).lower():
        return "vintage"
    return None


@st.cache_data(show_spinner=False, ttl=3600)
def find_places(lat: float, lon: float, radius: int):
    around = f"(around:{radius},{lat},{lon})"
    query = f"""
    [out:json][timeout:25];
    (
      nwr["amenity"="cafe"]{around};
      nwr["shop"="books"]{around};
      nwr["shop"~"^(music|records|musical_instrument)$"]{around};
      nwr["shop"~"^(second_hand|antiques)$"]{around};
      nwr["shop"="clothes"]["second_hand"~"^(yes|only)$"]{around};
    );
    out center tags 150;
    """
    last_err = None
    for url in OVERPASS_URLS:
        try:
            r = requests.post(url, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=40)
            r.raise_for_status()
            elements = r.json().get("elements", [])
            break
        except Exception as e:  # try the next mirror
            last_err = e
    else:
        raise RuntimeError(f"OpenStreetMap place search failed: {last_err}")

    places = []
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name")
        cat = classify(tags)
        if not name or not cat:
            continue
        plat = el.get("lat") or el.get("center", {}).get("lat")
        plon = el.get("lon") or el.get("center", {}).get("lon")
        if plat is None or plon is None:
            continue
        places.append(
            {
                "name": name,
                "category": cat,
                "lat": plat,
                "lon": plon,
                "cuisine": tags.get("cuisine", ""),
                "website": tags.get("website") or tags.get("contact:website", ""),
                "hours": tags.get("opening_hours", ""),
            }
        )
    return places


def haversine_m(a, b):
    r = 6371000
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


# ---------- Itinerary ----------
def score_place(p, center, qloo_names):
    s = 0.0
    if any(p["name"].lower() in q.lower() or q.lower() in p["name"].lower() for q in qloo_names):
        s += 5  # Qloo also recommends this place
    s += 1 if p["website"] else 0
    s += 0.5 if p["hours"] else 0
    s -= haversine_m(center, (p["lat"], p["lon"])) / 1000  # prefer closer to the center
    return s


def build_itinerary(places, center, qloo_names, max_stops=5):
    best = {}
    ranked = sorted(places, key=lambda p: score_place(p, center, qloo_names), reverse=True)
    for p in ranked:  # best place for each category first
        best.setdefault(p["category"], p)
    chosen = list(best.values())
    for p in ranked:  # fill up to max_stops with next best, any category
        if len(chosen) >= max_stops:
            break
        if p not in chosen:
            chosen.append(p)
    # Walking order: nearest-neighbor starting from the neighborhood center
    route, here, remaining = [], center, chosen[:]
    while remaining:
        nxt = min(remaining, key=lambda p: haversine_m(here, (p["lat"], p["lon"])))
        nxt = dict(nxt, leg_m=haversine_m(here, (nxt["lat"], nxt["lon"])))
        route.append(nxt)
        remaining = [p for p in remaining if p["name"] != nxt["name"]]
        here = (nxt["lat"], nxt["lon"])
    return route


# ---------- Gemini ----------
def explain_with_gemini(stops, matched, raw_tastes, neighborhood, api_key, model):
    taste_lines = []
    for m in matched:
        tag_txt = ", ".join(m["tags"]) if m["tags"] else "no tags returned"
        taste_lines.append(f'- {m["category"]}: {m["name"]} (Qloo taste tags: {tag_txt})')
    for cat, names in raw_tastes.items():
        for n in names:
            if not any(m["input"] == n for m in matched):
                taste_lines.append(f"- {cat}: {n} (not matched by Qloo)")
    stop_lines = [
        f'- {s["name"]} ({CATEGORY_LABELS[s["category"]]}'
        + (f', cuisine: {s["cuisine"]}' if s["cuisine"] else "")
        + ")"
        for s in stops
    ]
    prompt = (
        f"A person who likes the following lives near {neighborhood}.\n"
        + "\n".join(taste_lines)
        + "\n\nFor each place below, write 1-2 sentences on why it fits their taste. "
        "Be specific about the link to their favorites. Do not invent facts about the place "
        "(menu, history, decor) beyond its name and type; talk about the vibe it likely offers "
        'for someone with these tastes. Reply ONLY as JSON: [{"name": "...", "why": "..."}]\n\n'
        + "\n".join(stop_lines)
    )
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        },
        timeout=60,
    )
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return {item["name"]: item["why"] for item in json.loads(text)}


# ---------- UI ----------
def split_list(text: str):
    return [x.strip() for x in text.replace("\n", ",").split(",") if x.strip()]


st.title("🌱 LocalRoot")
st.caption("Tell us what you love. We'll turn it into a walk through your neighborhood.")

with st.form("taste_form"):
    films = st.text_input("Favorite films (comma separated)", placeholder="Amélie, Lost in Translation")
    music = st.text_input("Favorite music / artists", placeholder="Khruangbin, Nina Simone")
    design = st.text_input("Favorite design / brands", placeholder="Muji, Dieter Rams, IKEA")
    neighborhood = st.text_input("Neighborhood", placeholder="Indiranagar, Bengaluru")
    radius = st.slider("Search radius (meters)", 500, 3000, 1500, step=250)
    go = st.form_submit_button("Find my route")

if go:
    raw_tastes = {"films": split_list(films), "music": split_list(music), "design": split_list(design)}
    if not neighborhood.strip() or not any(raw_tastes.values()):
        st.warning("Please enter at least one favorite thing and a neighborhood.")
        st.stop()

    try:
        qloo_key = st.secrets["QLOO_API_KEY"]
        gemini_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        st.error("Missing keys. Add QLOO_API_KEY and GEMINI_API_KEY to your Streamlit secrets (see README).")
        st.stop()
    qloo_base = st.secrets.get("QLOO_BASE_URL", DEFAULT_BASE_URL)
    gemini_model = st.secrets.get("GEMINI_MODEL", GEMINI_MODEL_DEFAULT)

    # 1. Qloo: match each taste
    matched, qloo_names = [], []
    with st.status("Reading your taste with Qloo...", expanded=False) as status:
        try:
            qloo = QlooClient(qloo_key, qloo_base)
            matched, missed = qloo.match_all(raw_tastes)
            if matched:
                try:
                    qloo_names = qloo.taste_places([m["entity_id"] for m in matched], neighborhood)
                except QlooError:
                    qloo_names = []  # place boost is optional
            status.update(label=f"Qloo matched {len(matched)} of {len(matched) + len(missed)} tastes", state="complete")
            if missed:
                st.info("Qloo couldn't find: " + ", ".join(missed))
        except QlooError as e:
            status.update(label="Qloo unavailable, continuing with your raw tastes", state="error")
            st.warning(str(e))

    if matched:
        with st.expander("Your taste profile (from Qloo)"):
            for m in matched:
                st.write(f"**{m['name']}** ({m['category']}): " + (", ".join(m["tags"]) or "no tags"))

    # 2. OpenStreetMap: find places
    try:
        with st.spinner("Finding cafes, bookstores, music and vintage shops..."):
            geo = geocode(neighborhood)
            if not geo:
                st.error("Couldn't find that neighborhood. Try adding the city, e.g. 'Indiranagar, Bengaluru'.")
                st.stop()
            lat, lon, label = geo
            places = find_places(lat, lon, radius)
    except Exception as e:
        st.error(f"Map search failed: {e}")
        st.stop()

    if len(places) < 2:
        st.warning("Found very few places. Try a bigger radius or a more specific neighborhood.")
        st.stop()

    route = build_itinerary(places, (lat, lon), qloo_names)

    # 3. Gemini: explain
    whys = {}
    try:
        with st.spinner("Asking Gemini why each stop fits you..."):
            whys = explain_with_gemini(route, matched, raw_tastes, neighborhood, gemini_key, gemini_model)
    except Exception as e:
        st.warning(f"Gemini couldn't write the explanations ({e}). Showing the route without them.")

    # 4. Show itinerary
    st.subheader(f"Your walk near {neighborhood}")
    total_m = sum(s["leg_m"] for s in route[1:])
    st.caption(f"{len(route)} stops, about {total_m/1000:.1f} km ({round(total_m / WALK_M_PER_MIN)} min of walking between stops)")
    st.map([{"lat": s["lat"], "lon": s["lon"]} for s in route])

    for i, s in enumerate(route, 1):
        with st.container(border=True):
            st.markdown(f"### {i}. {s['name']}  \n*{CATEGORY_LABELS[s['category']]}*")
            if i > 1:
                st.caption(f"🚶 {round(s['leg_m'])} m from previous stop (~{max(1, round(s['leg_m'] / WALK_M_PER_MIN))} min)")
            if whys.get(s["name"]):
                st.write(whys[s["name"]])
            if s["website"]:
                st.markdown(f"[Website]({s['website']})")
    st.caption("Map data © OpenStreetMap contributors. Taste data by Qloo. Explanations by Gemini.")
