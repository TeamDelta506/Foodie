# Common Questions — Week 8 (Part B)

**Name:** Sam  
**Role:** Server-side (OAuth, gunicorn, backend hardening)

---

**1. What does nginx do that your Flask app shouldn't or can't?**

nginx terminates TLS — it decrypts HTTPS before the request reaches Python.
Flask can't do this itself without bundling a TLS library into the app process,
which mixes concerns. nginx also serves static files directly from disk without
hitting Python at all, enforces rate limits at the connection level before any
application code runs, and applies security headers to every response regardless
of which route handled it. If I put security headers in Flask, a route that
forgets to call `make_response()` could silently omit them. In nginx, they're
applied globally and unconditionally.

---

**2. What does gunicorn do that `flask run` doesn't?**

Two big things. First, it runs multiple worker processes simultaneously —
`flask run` handles one request at a time. With gunicorn's 3 workers, three
requests can be in-flight concurrently. Second, it never exposes the
interactive debugger. `flask run` with `debug=True` gives anyone who triggers
an unhandled exception a live Python shell in their browser — that's effectively
a remote code execution endpoint. gunicorn has no debug mode; uncaught
exceptions return a plain 500 and get logged to stderr. It also handles graceful
restarts — workers finish their current requests before dying, so a deploy
doesn't drop connections mid-flight.

---

**3. What's one specific thing your stack is now harder to misuse than it was
last week?**

The session cookie now has `SESSION_COOKIE_SECURE = True` active for real.
Last week the flag was set in the code but inert — `flask run` served plain
HTTP on port 5000, so the browser refused to set the cookie at all when Secure
was true, and I had to temporarily disable it for testing. This week, nginx
terminates HTTPS on port 443 and `ProxyFix` makes Flask see
`request.is_secure = True`, so the cookie is set with the Secure flag on.
A network attacker intercepting HTTP traffic between the client and a router
never sees the session cookie, because the cookie is only sent over HTTPS.

---

**4. If you wanted to add a load balancer to this picture, where would it go,
and what problem would it solve that nginx isn't already solving?**

It would go in front of nginx:

```
Browser → Load balancer → Host A (nginx → gunicorn → Flask)
                        → Host B (nginx → gunicorn → Flask)
                                  ↓
                              Postgres (shared)
```

nginx on a single host scales vertically — you can add workers, but you're
still on one machine that can fail. A load balancer distributes traffic across
multiple hosts and has health checks that stop routing to a host that's down.
nginx alone can't do this because it doesn't know there's a second nginx
somewhere else. nginx *is* a capable load balancer for traffic hitting one host,
but it can't make the problem of "this host is dead" go away on its own.

---

**5. What's a single point of failure in your current setup?**

The Postgres container. Every read and write in the app goes through it. If it
crashes or the host's disk fills up, the entire app breaks — all three gunicorn
workers fail on every DB-touching request simultaneously. We have
`restart: unless-stopped` in docker-compose.yml, which auto-restarts the
container after a crash, but there's a window where requests fail during the
restart. There's no replica to fall back to and no automated failover. A
primary-replica setup with failover would address this.

---

**6. If someone runs `docker-compose down` on production, what happens to the
data in your database?**

The data survives. Our compose file declares Postgres storage as a named Docker
volume called `pgdata`:

```yaml
volumes:
  - pgdata:/var/lib/postgresql/data
```

`docker-compose down` stops and removes containers and networks, but named
volumes are explicitly preserved — Docker requires `docker-compose down -v` to
also remove volumes. So the Postgres data directory persists on the host even
after all containers are gone. Running `docker-compose up` again reconnects the
same `pgdata` volume and the database is exactly as it was. The risk is
`docker-compose down -v` (or `docker volume rm`) — that deletes the volume
and the data is gone.

---

**7. What's one thing you learned about your stack from your LLM this week
that surprised you, and why?**

The slowloris attack. I knew rate limiting protected `/login` from password
brute-force, but I didn't realise nginx could be exhausted at the connection
layer by an attacker that opens many connections and sends request headers one
byte at a time — never completing the request, so gunicorn workers sit waiting.
No URL path is involved, so our `attack_paths.json` test gives no coverage
here at all. The fix is a few timeout directives I hadn't thought to set
(`client_header_timeout`, `client_body_timeout`) — trivial to add, but I
wouldn't have known to look for it. It changed how I think about what "rate
limiting" actually covers: it throttles request rates at the app level but does
nothing about connection-layer resource exhaustion.
