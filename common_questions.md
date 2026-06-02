# Common questions — Foodie production stack


1. What does nginx do that your Flask app shouldn't or can't?

nginx is the front door. It sits between the internet and the Python app and handles jobs that Flask is not built to do well on its own:

| Job | What nginx does | Why not only Flask? |
|-----|-----------------|---------------------|
| HTTPS (TLS) | Terminates SSL using certs in nginx/certs/ | Flask’s dev server is not a production TLS server; you want encryption handled by software designed for it. |
| Serve static files | Serves /static/ directly from disk (nginx/nginx.conf) | Faster and lighter than running every CSS/JS/image request through Python. |
| Rate limiting | Limits /login to about 5 requests per minute per IP | Protects against password-guessing floods without adding that logic to every route in Flask. |
| Security headers | Adds HSTS, X-Frame-Options, CSP, etc. on every response | One place to enforce policy for all pages, including errors. |
| Reverse proxy | Forwards other requests to gunicorn over a unix socket | Flask/gunicorn stay off the public internet; nginx is the only thing exposed on ports 80/443. |

Simple analogy: Flask is the kitchen. nginx is the host at the door (checks ID, stops crowding at the login desk, hands out menus from a shelf without bothering the chef).

---

2. What does gunicorn do that flask run doesn't?

flask run is meant for development: one process, auto-reload, not safe or fast enough for real traffic.

gunicorn is a production WSGI server. It runs your Flask app (yourapp:create_app() in the Dockerfile) as a real service:

- Multiple workers (workers = 3 in gunicorn.conf.py) — several requests at once; flask run handles one at a time in practice.
- Stable process model — if one worker hangs, others can still answer; gunicorn can restart workers (timeout = 30).
- Listens on a unix socket (unix:/tmp/gunicorn.sock) — pairs with nginx instead of exposing Flask on port 5000.
- No debug mode — avoids leaking stack traces and unsafe dev behavior to users.

---

3. "Hardening" means making something harder to misuse. What's one specific thing your stack is now harder to misuse than it was last week?

**Example: rate limiting on /login.

Before nginx, someone could script thousands of login attempts against your app. Now nginx/nginx.conf has:

```nginx
limit_req zone=login burst=3 nodelay;
```

on /login (5 requests per minute per IP, with a small burst). Extra attempts get rejected at nginx before they hit Flask or the database.

That is concrete hardening: abuse of the login form is harder, not because you rewrote Flask, but because the edge blocks it.

---

4. If you wanted to add a load balancer to this picture, where would it go, and what problem would it solve that nginx isn't already solving?

Where it goes: In front of nginx — between users and your server(s).

```
Browser → Load balancer → nginx (on each app server) → gunicorn → Flask → Postgres
```

What nginx already solves (on one machine):

- TLS, static files, rate limits, proxying to gunicorn on that host.

What a load balancer adds that nginx does not:

- Spread traffic across multiple machines running the same stack (horizontal scaling).
- Health checks — stop sending users to a dead or unhealthy server.
- Survive one server dying — traffic shifts to others (nginx on a single box is still one machine; if the VM dies, everything on it is down).

---

5. What's a single point of failure in your current setup?

More than one answer is fine. Pick one you understand well:

 The one db container - All users, recipes, and meal plans are unavailable — the app cannot read or write data. Currently we have three containers, but they often run on one computer. That computer (or the database volume on it) is a choke point.

---

6. If someone runs docker compose down on production, what happens to the data in your database?
If somebody runs the doccer compose down command then it will:

- Stops and removes the containers (nginx, app, db).
- Does not remove named volumes by default.
- pgdata stays on disk — your users, recipes, and meal plans should still be there when you run docker compose up again.

---

7. What's one thing you learned about your stack from your LLM this week that surprised you, and why?

I was surprised that gunicorn and nginx talk through a unix socket file (/tmp/gunicorn.sock) instead of HTTP on port 8000. I assumed everything used URLs and ports. I learned that a socket is just a file both containers share via the gunicorn-socket volume, It is faster and not exposed to the network. I stopped thinking of nginx as another web app and saw it as a local pipe into gunicorn, with only nginx facing the public internet on 443.
