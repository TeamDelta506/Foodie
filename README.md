# 🍽️ Foodie  
**Project:** Recipe Scaler and Meal Planner  

---

## 👥 Team & Roles
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

### 2. Start with Docker Compose

From the **repo root** (the directory that contains `app.py` and `docker-compose.yml`):

```bash
docker compose up --build -d
```

Open [http://localhost:5000](http://localhost:5000). Register a user, log in, and try **Discover recipes** search.

Verify Edamam keys are loaded in the app container:

```bash
docker compose exec app printenv EDAMAM_APP_ID EDAMAM_APP_KEY
```

If either line is empty, check that `.env` exists in the same directory as `docker-compose.yml` and restart: `docker compose up -d`.

### 3. Run tests

```bash
python3 -m pytest tests/test_db_schema_and_auth.py tests/test_auth.py -v
```

Postgres constraint checks and the full e2e walk are documented in `e2e/db_security.md`.

### 4. Deployed / shared server

Set the same environment variables on the host (AWS, Render, etc.) or in your deployment secrets — not in source code. All users of that deployment share one Edamam quota; cached recipes in Postgres reduce repeat API calls.

---

## 💡 Why This Project

We chose to build a meal planner because it is a practical tool that solves a real everyday problem while also giving us a chance to work on meaningful technical challenges. Sam is particularly motivated by the opportunity to design a system that supports healthy eating habits and aligns with his interest in maintaining a balanced lifestyle. Justin is interested in building a tool he can also use personally to support a healthier routine after transitioning out of active duty military life, and he is especially curious about learning more about application security in a real-world project. Asia chose this project because she finds meal planning genuinely useful in her own life and often struggles with finding recipes; she is also excited to strengthen her frontend skills by working with JavaScript and CSS to create a polished, realistic user experience.

---
