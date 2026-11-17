# Material Estimator — FastAPI edition

The Outsulation Plus MD Material Estimator with a **Python FastAPI** backend. It has the same features
as the Next.js app (accounts, Google sign-in, guest mode, saved estimates, admin, PDF/Excel), but
**every material quantity is calculated in Python** by a verified port of `calculator_v8.html`.

This is a separate app. The Next.js app, its GitHub repository and its Vercel project are not
changed by anything here, and this app should use its **own Supabase project**.

## How it works

| Part | What it does |
|---|---|
| `app/engine.py`, `app/jsnum.py` | The calculator, ported line by line from `calculator_v8.html`, with JavaScript's number rules reproduced exactly |
| `app/main.py` | All pages and APIs (FastAPI + Jinja templates) |
| `app/supa.py`, `app/session.py` | Supabase sign-in and database calls; sessions in secure httpOnly cookies |
| `app/exports.py` | PDF (ReportLab) and Excel (openpyxl), built from the Python results |
| `public/static/estimator-ui.js` | The calculator **screens**, copied verbatim from `calculator_v8.html` by `tools/build_ui.mjs`. Its own `compute()`/`lineInfo()` are replaced by calls to `/api/calc`, so the numbers come from Python |
| `supabase/schema.sql`, `seed_products.sql` | Database tables, security rules and the 56 verified products |

Saving and exports never trust numbers from the browser: the server recalculates from the inputs,
using the estimate's own saved product values when it is reopened.

## Proof that the numbers are unchanged

| Check | Command |
|---|---|
| Python engine vs original JavaScript, 8,600 input sets incl. edge cases | `node tools/make_cases.mjs` then `pytest tests/test_parity.py` |
| App screens vs original page, 500 random projects (side panel after every page, review table, material lines, validation stops) | start the server, then `node tools/ui_parity.mjs 50 1` (repeat with seeds 51, 101, …) |
| Pages, APIs, safety rules | `pytest tests/test_app.py` |

The tools need Node.js and `cd tools && npm install` once (jsdom; not deployed).

## Run locally
```
python -m venv .venv
.venv\Scripts\activate                 (macOS/Linux: source .venv/bin/activate)
pip install -r requirements-dev.txt
copy .env.example .env                 (fill in, see below; optional for the calculator alone)
uvicorn app.main:app --reload --env-file .env
```
Open http://127.0.0.1:8000. Without Supabase settings, the home page, guest calculator, PDF and
Excel work; sign-in and saving need Supabase. API docs: http://127.0.0.1:8000/api/docs

## Set up (new Supabase project + Vercel)

1. **Supabase**: create a NEW project (supabase.com → New project).
   - SQL Editor: run `supabase/schema.sql`, then `supabase/seed_products.sql`.
   - Authentication → URL Configuration: Site URL = your Vercel address; Redirect URLs =
     `https://<your-app>.vercel.app/**` and `http://127.0.0.1:8000/**`.
   - Google sign-in (optional): same steps as the Next.js app's README, with this project's callback URL.
   - Project Settings → API: copy the Project URL and the publishable key.
2. **GitHub**: push this folder to a NEW repository.
3. **Vercel**: Add New → Project → import the new repository. Framework preset: **Other**.
   Environment variables (type **Config**): `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`. Deploy.
4. First admin: in the SQL Editor, `update public.profiles set role = 'admin' where email = 'you@example.com';`

Vercel detects the FastAPI app in `app/main.py` automatically (no `vercel.json` needed); files in
`public/` are served directly by Vercel's CDN.

## Updating the calculator screens
If `reference/calculator_v8.html` is replaced by a new verified version: run `node tools/build_ui.mjs`,
port any calculation changes to `app/engine.py`, copy the new product/step data into `app/data/`,
then re-run all three checks above.
