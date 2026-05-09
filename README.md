# Course 506 Week 5 Skeleton

Flask + Postgres + SQLModel + Bootstrap, plus a sliver of vanilla JavaScript where it earns its keep.

This is the starter for the Week 5 individual assignment and the seed for your team project's repo. Every team member builds their own copy of this skeleton; your team coordinates one shared artifact (the About page).

The home page serves your S3 static site — every student's app shows their own content.

## Running it

You need Docker and Docker Compose installed. Both come with Docker Desktop on macOS and Windows; on Linux they're separate packages.

From the repo root:

```bash
docker compose up
```

The app is available at http://localhost:5000

First run: Compose pulls the Postgres image, builds the Flask container, and runs both. ~30 seconds.
Subsequent runs: ~3 seconds.

Stop with `Ctrl-C`. Restart any time with `docker compose up`.

## Sync your S3 content

The home page serves whatever you have in the `S3_content/` folder. Populate it from your S3 bucket using the AWS CLI you set up in Week 4:

```bash
aws s3 sync s3://<your-bucket>/ S3_content/
```

You should see your `index.html` and any other files copy down. When you load the home page, Flask serves them.

If you skip this step, the home page shows a friendly placeholder reminding you to run the sync.

## Running on EC2

Same commands. SSH to your EC2 (you've been doing this since Week 4), clone this repo into `~/`, run the S3 sync, and `docker compose up`. Then on your laptop, port-forward port 5000:

```bash
ssh -i ~/.ssh/your-key.pem -L 5000:localhost:5000 ubuntu@<EC2_IP>
```

Open http://localhost:5000 in your laptop's browser. You should see your S3 site, served by Flask.

## Layout

```
app.py                 Flask application — all routes in one file
S3_content/            Your synced S3 site (gitignored; you populate this)
templates/             Flask-rendered Jinja2 templates (login, register, about, placeholder)
static/                Flask's own CSS and JavaScript (the JS sliver lives here)
tests/                 pytest tests, run on every PR via GitHub Actions
docker-compose.yml     Two services — app (Flask) and db (Postgres)
Dockerfile             Builds the Flask container
requirements.txt       Python dependencies
contracts/             Empty for Week 5; populated next week
.github/workflows/     GitHub Actions — runs pytest on every PR
```

## Routes

| Route | Served by | What |
|---|---|---|
| `/` | `templates/home.html` | Flask-rendered landing page with navbar (links to /site/, /about, /login, /register) |
| `/site/` | `S3_content/index.html` | Your S3 site's home page |
| `/site/<anything>` | `S3_content/<file>` | Any other file from your bucket (CSS, JS, images, nested folders) |
| `/login` | `templates/login.html` | Flask-rendered login form |
| `/register` | `templates/register.html` | Flask-rendered register form |
| `/logout` | redirect | POST-only; clears session |
| `/about` | `templates/about.html` | Flask-rendered about page (your team replaces) |

The Flask-rendered pages all share `templates/base.html`, which gives them a navbar with "My Site," "About," "Login/Register" or "Hello, *username* / Log out." Click "My Site" to view your synced S3 content.

## The assignment in one paragraph

Get the skeleton running, sync your S3 content, register an account, log in, see the JS-sliver double-submission bug and enable the fix, customize at least one Bootstrap thing, push a PR with passing CI. Your team agrees on the eight-section About page and every team member's `templates/about.html` matches. See the assignment doc on Canvas for the full rubric.
