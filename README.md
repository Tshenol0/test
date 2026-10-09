# Mini PaaS

A self-hosted "describe it, get a live site" platform: React + FastAPI +
PostgreSQL for the platform itself (accounts, login), plus a **PaaS layer**
that lets a logged-in, non-technical user type a plain-language description
of a business, and get back a real, working, deployed website — generated
code, its own database, its own container, its own subdomain — with no
code written by the user.

This mirrors the flow: `user prompt -> AI agent -> generates application ->
build application -> Docker container -> deploy -> subdomain.yourpaas.com`.

## Stack
- **Platform frontend:** React 18 (react-router-dom), dev server on port 3000
- **Platform backend:** FastAPI + SQLAlchemy + passlib (bcrypt) + python-jose (JWT)
- **Platform database:** PostgreSQL 16 (`db`), holds users + project metadata
- **Apps database:** a second PostgreSQL 16 instance (`apps-db`) — every
  generated site gets its own database on this shared instance
- **Traefik v3**: reverse proxy that discovers each generated site's
  container via Docker labels and routes `<subdomain>.<BASE_DOMAIN>` to it
- **Generator:** a template-based "AI Agent" (see caveat below) that turns
  a name + description into a small full-stack app (FastAPI + vanilla-JS
  static frontend + Postgres schema: products, contact messages, cart, orders)

## Project layout
```
fullstack-app/
├── docker-compose.yml
├── .env.example
├── generated-apps/            # generated sites land here (gitignored contents)
├── db/
│   └── init.sql               # platform DB: users table
└── backend/
    ├── Dockerfile
    ├── requirements.txt
    └── app/
        ├── main.py            # FastAPI app, mounts /projects router
        ├── database.py
        ├── models.py          # User, Project
        ├── schemas.py
        ├── auth.py            # hashing + JWT
        ├── crud.py
        ├── generator.py       # the "AI Agent": description -> app files
        ├── docker_manager.py  # build/run containers, create per-project DB
        └── projects_routes.py # /projects create/list/redeploy/delete
└── frontend/
    ├── Dockerfile
    ├── package.json
    └── src/
        ├── App.js
        ├── api.js
        └── pages/
            ├── Login.js, Register.js, Home.js
            └── Projects.js    # create a site, watch status, open/redeploy/delete
```

## Running it

1. Copy the env file:
   ```bash
   cp .env.example .env
   ```

2. Build and start everything:
   ```bash
   docker compose up --build
   ```

3. Open the platform:
   - Frontend: http://localhost:3000
   - Backend docs: http://localhost:8000/docs
   - Traefik dashboard (dev only): http://localhost:8080

4. Register, log in, go to **"Manage your sites"**, and create one:
   - Name: `Luna Clothing Co.`
   - Description: `I want a website for my clothing business. It should
     have a homepage, products page, contact form and shopping cart.`

   Watch the status go `Queued -> Generating -> Building & deploying ->
   Live`, then click **Open site**. It's reachable at
   `http://luna-clothing-co.yourpaas.localhost` — real HTML, real API,
   real database, its own container.

   `*.localhost` domains resolve to `127.0.0.1` automatically in Chrome,
   Edge and Firefox — no DNS or hosts-file changes needed for local use.

## How the PaaS part works

1. **Create** (`POST /projects`): picks a unique subdomain from the site
   name, detects a rough category from the description (clothing / food /
   tech / services) and stores the project as `created`.
2. **Generate** (background task, `generator.py`): fills in a small
   FastAPI + static-HTML template for that category — real product data,
   a working cart, a contact form — and writes it to
   `generated-apps/<subdomain>/`.
3. **Provision a database** (`docker_manager.create_app_database`): creates
   a fresh Postgres database on the shared `apps-db` instance and runs the
   generated schema/seed SQL against it.
4. **Build & deploy** (`docker_manager.build_and_run`): builds a Docker
   image from the generated source (via the Docker SDK talking to the
   host's Docker socket) and starts it as its own container, labeled for
   Traefik: `Host(\`<subdomain>.yourpaas.localhost\`)`.
5. **Redeploy/Delete**: redeploy re-runs steps 2-4 in place; delete removes
   the container and drops its database.

The platform's own frontend polls `GET /projects` every ~2.5s while
anything is still generating/building, so the UI updates itself without
the user doing anything.

## Important caveats (read before treating this as production-ready)

- **The "AI" is a template engine, not a model call.** `generator.py`
  picks from a handful of built-in categories by keyword matching. It's
  written so the *interface* (`generate_site(name, description) -> {files,
  init_sql, category}`) is exactly what you'd need to swap in a real LLM
  call (e.g. the Anthropic API) later — nothing else in the pipeline
  would need to change.
- **The Docker socket is mounted into the backend container.** This is
  what lets the backend build/run *other* containers (the standard
  "sibling containers" pattern used by Dokku/Coolify/CapRover), but it is
  equivalent to giving that container root on the host. Fine for a local
  demo; not something to expose publicly as-is.
- **Generated sites share one Postgres instance and one admin credential**
  (`apps-db` / `apps_admin`), just with separate databases. That's a
  reasonable simplification for a portfolio project, but it's not
  real tenant isolation — a compromised generated app's container could
  reach every other generated app's database.
- **No HTTPS.** Traefik here only has an unencrypted `web` entrypoint on
  port 80. For anything beyond localhost you'd add a `websecure`
  entrypoint + a TLS resolver (Let's Encrypt) to Traefik.
- **Subdomains only resolve locally.** `yourpaas.localhost` works on your
  machine; putting this on a real domain means pointing real DNS
  (a wildcard `*.yourpaas.com` record) at the host running Traefik.

## Resetting

```bash
docker compose down -v   # drops db_data AND apps_db_data volumes
rm -rf generated-apps/*  # clears generated source on disk
```

Note: `down -v` does **not** remove the individually-created containers
for each deployed site (they aren't part of docker-compose) — delete
those from the Projects page first, or `docker rm -f $(docker ps -aq
--filter "name=paas-app-")`.
