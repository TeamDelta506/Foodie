# 🍽️ Foodie  
**Project:** Recipe Scaler and Meal Planner  

---

## 📚 Documentation

Team specs, walkthroughs, and e2e guides live under [`docs/`](docs/):

| Doc | Purpose |
|-----|---------|
| [`docs/CONTRACTS.md`](docs/CONTRACTS.md) | Binding API / schema contract |
| [`docs/team_walkthrough.md`](docs/team_walkthrough.md) | Week 7 whole-system walkthrough |
| [`docs/e2e.md`](docs/e2e.md) | Coordinator Saturday e2e narrative |
| [`docs/e2e/`](docs/e2e/) | Per-role slice walks (client, server, DB) |

---

## 👥 Team & Roles
- **Sowmya** – runs the coordinating-LLM session that produces contracts, owns [`docs/CONTRACTS.md`](docs/CONTRACTS.md), reviews cross-role PRs, runs integration tests on the shared EC2.
- **Sam** – server-side development, backend logic, API integration  
- **Asia** – client-side development, UI/UX, frontend implementation (JavaScript & CSS)  
- **Justin** – database management, security considerations, system design  

---

## 👤 Target User
This app is for people who want an easy way to plan their meals and adjust recipes without doing manual calculations. Their goal is to quickly build a weekly meal plan and automatically scale recipes based on how many servings they need.

---

## 🚀 MVP (Version 1)

The minimum viable product for this project is a simple Recipe Scaler and Meal Planner web app focused on generating meals and adjusting portions.

### Core Features:
- **Recipe search and selection using Edamam API**  
  Users can search for recipes and view basic details like ingredients and nutrition information.

- **Recipe scaling feature**  
  Users can adjust the number of servings, and the app automatically scales ingredient quantities.

- **Basic meal plan creation**  
  Users can assign selected recipes to days in a simple weekly planner view.

- **Nutrition display per recipe**  
  Show calories and basic macronutrients (protein, carbs, fat) per serving.

- **Simple user interface**  
  A clean and functional frontend where users can browse recipes, scale them, and build a meal plan.

---

## 🔌 External APIs

The primary API for this project is the **Edamam Recipe API**, which provides a ready-made recipe database along with nutrition data. This allows us to focus on building application features rather than maintaining our own dataset.

Edamam requires authentication using an app ID and API key. Its free tier is limited, supporting only a small number of users (around 10 monthly active users), with request limits per user per day and restrictions on caching or storing recipe data. Because of these constraints, it is best suited for a demo or portfolio project rather than large-scale production.

As a backup, we will use the **USDA FoodData Central API**. It also requires an API key but is fully free and provides higher rate limits (around 1,000 requests per hour per IP). However, it only includes raw food and nutrition data without recipes or images, meaning additional logic would be needed to support full meal-planning features.

---

## 🛠️ Team setup (run locally)

Foodie has two kinds of credentials:

| Kind | Who needs it | Where it lives |
|------|----------------|----------------|
| **Foodie account** (register / login) | Each person using the app | Postgres `users` table |
| **Edamam API keys** | The team / server (once) | `.env` on the machine running Flask |

End users do **not** need their own Edamam account. The server reads one `EDAMAM_APP_ID` and `EDAMAM_APP_KEY` from the environment and uses them for every recipe search.

### 1. Clone and configure environment

```bash
git clone https://github.com/TeamDelta506/Foodie.git
cd Foodie
git checkout week6/db&security   # or your feature branch
cp .env.example .env
```

Edit `.env` and set (get these from [Edamam Developer](https://developer.edamam.com/) → Recipe Search API app):

```bash
EDAMAM_APP_ID=your-application-id
EDAMAM_APP_KEY=your-application-key
```

Optional overrides (see `.env.example`): `SECRET_KEY`, `DATABASE_URL`.

Share the Edamam values with teammates through a **secure** channel (password manager, DM). Do not commit `.env` or post keys in GitHub issues or PRs.

### 2. Start with Docker Compose (production stack)

From the **repo root** (the directory that contains `app.py` and `docker-compose.yml`):

```bash
mkdir -p nginx/certs
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout nginx/certs/key.pem -out nginx/certs/cert.pem \
  -days 365 -subj "/CN=localhost"
docker compose up --build -d
```

Open [https://localhost](https://localhost) (accept the self-signed certificate warning). Set `SECRET_KEY` in `.env` before starting (see `.env.example`).

**Development** (Flask dev server on port 5000, no nginx):

```bash
docker compose -f docker-compose.dev.yml up --build -d
```

Open [http://localhost:5000](http://localhost:5000). Verify Edamam keys:

```bash
docker compose -f docker-compose.dev.yml exec app printenv EDAMAM_APP_ID EDAMAM_APP_KEY
```

---

## 🧱 Running the production stack (Week 8: nginx + gunicorn + Postgres)

This stack runs the app behind **nginx** (TLS on 443) proxying to **gunicorn** over a **unix socket**, with **Postgres** on the internal Docker network.

### 1. Ensure secrets exist

Create `.env` (gitignored) and set at least:

```bash
SECRET_KEY=your-long-random-secret
```

Optional (feature-related) values: `EDAMAM_APP_ID`, `EDAMAM_APP_KEY`, `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`.

### 2. Generate a self-signed cert (one-time, not committed)

The prod compose file mounts certs from `deploy/nginx/certs/` as `/etc/nginx/certs/` in the nginx container.

If you don't have `openssl` installed locally, this Docker command works:

```bash
docker run --rm -v "$(pwd)/deploy/nginx/certs:/certs" alpine/openssl req -x509 -newkey rsa:2048 -nodes -keyout /certs/key.pem -out /certs/cert.pem -days 365 -subj "/CN=localhost"
```

### 3. Start the production stack

From the repo root:

```bash
docker compose -f docker-compose.prod.yml up --build
```

Open `https://localhost` (your browser will warn because the cert is self-signed).

### 3. Run tests

```bash
python3 -m pytest tests/test_db_schema_and_auth.py tests/test_auth.py -v
```

Postgres constraint checks and the full e2e walk are documented in [`docs/e2e/db_security.md`](docs/e2e/db_security.md).

### 4. Deploy on Render

1. Push the repo and create a **Blueprint** from [`render.yaml`](render.yaml), or a **Web Service** with **Docker** and `Dockerfile.prod`.
2. Add a **Render Postgres** instance; link `DATABASE_URL` (set automatically if you use the blueprint).
3. In the Render dashboard, set `EDAMAM_APP_ID`, `EDAMAM_APP_KEY`, `OAUTH_CLIENT_ID`, and `OAUTH_CLIENT_SECRET` (`SECRET_KEY` can be auto-generated by the blueprint).
4. In your GitHub OAuth app, set the callback URL to `https://<your-service>.onrender.com/auth/github/callback`.
5. Do **not** set `ENABLE_TEST_LOGIN` on Render.

`Dockerfile.prod` runs Gunicorn on `0.0.0.0:$PORT`. The app enables secure cookies when `RENDER=true` (set automatically on Render).

### 5. Other deployed / shared servers

Set the same environment variables on the host (AWS, EC2, etc.) or in your deployment secrets — not in source code. All users of that deployment share one Edamam quota; cached recipes in Postgres reduce repeat API calls. For nginx + TLS, replace `yourapp.example.com` in `deploy/nginx/nginx.conf` and use real certificates (e.g. Let's Encrypt) in `deploy/nginx/certs/`.

---

## 💡 Why This Project

We chose to build a meal planner because it is a practical tool that solves a real everyday problem while also giving us a chance to work on meaningful technical challenges. Sam is particularly motivated by the opportunity to design a system that supports healthy eating habits and aligns with his interest in maintaining a balanced lifestyle. Justin is interested in building a tool he can also use personally to support a healthier routine after transitioning out of active duty military life, and he is especially curious about learning more about application security in a real-world project. Asia chose this project because she finds meal planning genuinely useful in her own life and often struggles with finding recipes; she is also excited to strengthen her frontend skills by working with JavaScript and CSS to create a polished, realistic user experience.

---
