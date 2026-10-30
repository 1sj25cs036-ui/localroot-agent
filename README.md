# 🌱 LocalRoot

Enter a few favorite films, music and design brands plus a neighborhood. LocalRoot uses
**Qloo** to understand your taste, **OpenStreetMap** (Nominatim + Overpass) to find cafes,
bookstores, music shops and vintage shops nearby, and **Gemini** to explain in 1-2 sentences
why each stop fits you. You get a 4-5 stop walking itinerary on a map.

## Files
- `app.py` – the Streamlit app
- `qloo_client.py` – Qloo API wrapper (base URL and endpoints live here)
- `requirements.txt` – Python packages

## Run it locally (step by step)
1. Install Python 3.10+.
2. In this folder, run: `pip install -r requirements.txt`
3. Create a folder named `.streamlit` and inside it a file `secrets.toml` with:
   ```toml
   QLOO_API_KEY = "your-qloo-key"
   GEMINI_API_KEY = "your-gemini-key"
   # optional:
   # QLOO_BASE_URL = "https://hackathon.api.qloo.com"
   # GEMINI_MODEL = "gemini-2.5-flash"
   ```
4. Run: `streamlit run app.py`

## Deploy free on Streamlit Community Cloud
1. Push these files to your public GitHub repo `localroot-agent` (add an MIT `LICENSE`).
2. At share.streamlit.io, create an app from the repo, main file `app.py`.
3. In the app's **Settings → Secrets**, paste the same lines as `secrets.toml`.
4. **Never commit `secrets.toml`.** Add `.streamlit/secrets.toml` to `.gitignore`.

## How it works
1. Qloo `/search` matches each favorite to a Qloo entity and its taste tags.
2. Qloo `/v2/insights` (places) gives a small ranking boost to matching OSM places.
3. Nominatim geocodes the neighborhood; Overpass fetches nearby cafes, bookstores, music
   and vintage shops.
4. The app picks the best place per category (up to 5), orders them into a walking route.
5. Gemini writes the "why this fits you" blurbs.

## Notes
- If Qloo or Gemini fails, the app still shows a route and says what was skipped.
- Nominatim/Overpass are free public services; please keep usage light.
