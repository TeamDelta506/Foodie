# Common Questions — Week 8 (Part B)

**Name:** Sam  
**Role:** Server-side (OAuth, gunicorn, backend hardening)

---

**1. What does nginx do that your Flask app shouldn't or can't?**

Terminates TLS, serves static files directly from disk, and applies security
headers to every response unconditionally — none of which belong in application
code.

---

**2. What does gunicorn do that `flask run` doesn't?**

Runs multiple worker processes concurrently and never exposes the interactive
debugger. `flask run` is single-threaded and a single unhandled exception gives
anyone a live Python shell in their browser.

---

**3. What's one specific thing your stack is now harder to misuse than it was
last week?**

`SESSION_COOKIE_SECURE = True` is actually active now. Last week it was set but
inert because there was no HTTPS. Now that nginx terminates TLS and ProxyFix
passes `X-Forwarded-Proto`, the cookie is only sent over HTTPS — a plain HTTP
request gets no session cookie at all.

---

**4. If you wanted to add a load balancer to this picture, where would it go,
and what problem would it solve that nginx isn't already solving?**

In front of nginx, distributing traffic across multiple hosts. nginx on one host
can't route around a dead host — a load balancer has health checks and fails
traffic away from a host that's down.

---

**5. What's a single point of failure in your current setup?**

The Postgres container. Every request that touches data depends on it. If it
goes down, the whole app breaks until it restarts.

---

**6. If someone runs `docker-compose down` on production, what happens to the
data in your database?**

It survives. Postgres data is stored in a named Docker volume (`pgdata`), which
`docker-compose down` doesn't touch. You'd need `docker-compose down -v` to
actually delete it.

---

**7. What's one thing you learned about your stack from your LLM this week
that surprised you, and why?**

Slowloris — an attacker opens many connections and dribbles headers one byte at
a time, never finishing the request, tying up gunicorn workers without ever
hitting a valid URL. Our rate limiting and attack-path tests give zero coverage
here. The fix is just setting `client_header_timeout` in nginx, which I
wouldn't have thought to add.
