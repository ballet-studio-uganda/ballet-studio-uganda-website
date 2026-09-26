# Deploying to Render

The repository carries a `render.yaml` blueprint, so Render can provision the
web service and the database together from one click. This is the walkthrough,
including the parts that are easy to get wrong.

---

## 1. Push to GitHub

The project is already a git repository with an initial commit. Create an empty
repository on GitHub — **no** README, .gitignore or licence, or the first push
will be rejected — then:

```bash
git remote add origin https://github.com/<you>/ballet-dance-studio-ug.git
git branch -M main
git push -u origin main
```

**Make it private.** The repository contains the studio's brand assets and, once
live, its deployment shape. Nothing secret is committed — `.env`, `db.sqlite3`
and `media/` are all ignored — but there is no reason for it to be public.

---

## 2. Create the services on Render

1. Sign in at <https://dashboard.render.com>.
2. **New → Blueprint**, and select the repository.
3. Render reads `render.yaml` and offers to create:
   - **bdsu** — the web service
   - **bdsu-db** — a PostgreSQL database
4. Click **Apply**.

The first build takes a few minutes. `build.sh` installs dependencies, collects
static files, migrates, seeds the reference data (programmes, terms, the skill
rubric, fee and expense categories, the hero placeholder), and creates the
director account if you set the variables in the next step.

---

## 2b. If you created the service by hand instead

Creating it as **New → Web Service** rather than **New → Blueprint** means Render
never reads `render.yaml`. It guesses instead, and its guess for Python is
`gunicorn app:app`, which fails immediately:

```
==> Running 'gunicorn app:app'
ModuleNotFoundError: No module named 'app'
```

`app:app` is a Flask convention. This project's WSGI entry point is
`ballet_dance_studio.wsgi:application`.

**The clean fix** is to delete the service and recreate it with
**New → Blueprint**. That is not a defeat — the blueprint also creates the
database, attaches the media disk, sets the health check and wires a dozen
environment variables, all of which you would otherwise re-enter by hand.

**To repair it in place instead**, set these under **Settings**:

| Setting | Value |
|---|---|
| Build Command | `./build.sh` |
| Start Command | `gunicorn ballet_dance_studio.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 60` |
| Health Check Path | `/healthz` |

then add the environment variables from section 3, create a PostgreSQL
instance and set `DATABASE_URL` from it, and attach a disk at `/var/media`
with `MEDIA_ROOT=/var/media`. At that point you have rebuilt `render.yaml` by
hand, which is why recreating from the blueprint is usually quicker.

A `.python-version` file pins Python to 3.14.3 either way, so that part is
handled whichever route you take.

---

## 3. Fill in the environment variables

`render.yaml` generates `DJANGO_SECRET_KEY` and wires `DATABASE_URL` for you.
These are the ones marked `sync: false`, which Render leaves blank on purpose —
set them under **Environment** on the web service.

### To create the first login (set these before the first deploy)

| Variable | Example |
|---|---|
| `DJANGO_SUPERUSER_USERNAME` | `director` |
| `DJANGO_SUPERUSER_EMAIL` | `director@balletdancestudioug.com` |
| `DJANGO_SUPERUSER_PASSWORD` | a long passphrase |

**Delete all three once you have signed in and changed the password.** They sit
in the environment in plain text, and the account they create outlives them.

### Once you have a custom domain

| Variable | Example |
|---|---|
| `DJANGO_ALLOWED_HOSTS` | `balletdancestudioug.com,www.balletdancestudioug.com` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://balletdancestudioug.com,https://www.balletdancestudioug.com` |

Until then you need neither: `settings.py` trusts `RENDER_EXTERNAL_HOSTNAME`,
which Render injects, so `bdsu.onrender.com` works out of the box.

### To send real email

Password resets and notifications are printed to the log until these are set:

| Variable | Notes |
|---|---|
| `EMAIL_HOST` | e.g. `smtp.gmail.com`, or a transactional service |
| `EMAIL_HOST_USER` | the sending account |
| `EMAIL_HOST_PASSWORD` | an app password, **not** the account password |

`EMAIL_PORT`, `EMAIL_USE_TLS` and `DEFAULT_FROM_EMAIL` already have sensible
values in the blueprint.

---

## 4. Uploads — read this one properly

This is the part that quietly loses data if it is skipped.

**A Render container's filesystem is wiped on every deploy.** The studio uploads
real things — the hero video, gallery photos, dancer portraits, photographs of
payment receipts. On a default Render service they would all vanish the next
time you push a change.

`render.yaml` therefore attaches a **persistent disk** at `/var/media` and points
`MEDIA_ROOT` at it. That is the simplest arrangement and it works, with two
caveats worth knowing:

- **Disks are a paid feature.** If your plan has no disk, remove the `disk:`
  block or the blueprint will not apply — and then use object storage instead
  (below), because without either one uploads do not survive.
- **A disk disables zero-downtime deploys.** The old container must release the
  disk before the new one can mount it, so each deploy has a short gap. At this
  scale that is a non-issue.

### The free alternative: object storage

Cloudinary's free tier handles both images and video, is CDN-backed, survives
deploys and costs nothing at this size. It needs a package and a storage
backend, which are deliberately **not** installed — so this is a change to make
deliberately, not something half-wired that might mislead you:

```bash
pip install django-cloudinary-storage cloudinary
```

then add `cloudinary` and `cloudinary_storage` to `INSTALLED_APPS`, point
`STORAGES['default']` at
`cloudinary_storage.storage.MediaCloudinaryStorage`, set `CLOUDINARY_URL` in the
environment, and set `SERVE_MEDIA=false` so Django stops trying to serve files
it no longer holds. Then drop the `disk:` block from `render.yaml`.

I have not run that path here, so treat it as a documented route rather than a
tested one.

### How media is served today

WhiteNoise serves `/static/` from inside the web process. Uploads sit outside
it, so `urls.py` serves `/media/` through Django when `SERVE_MEDIA` is on. That
occupies a worker for the length of each transfer — fine for a studio's traffic,
and the first thing to move behind a CDN if the gallery ever gets busy.

---

## 5. Free-tier realities

Worth saying plainly before the client sees the site:

- **The web service sleeps.** A free service spins down after about 15 minutes
  with no traffic, and the next visitor waits roughly 50 seconds for it to wake.
  Fine while you are showing work in progress; not fine for a public launch.
  The cheapest paid instance removes it.
- **The free database expires.** Render deletes free PostgreSQL instances after
  30 days. Upgrade it before then, or you lose everything in it. Set a reminder
  the day you deploy.
- **Take backups anyway.** On any plan:
  ```bash
  pg_dump "$DATABASE_URL" > bdsu-$(date +%F).sql
  ```

---

## 6. Deploying changes

Render watches the `main` branch. Push, and it rebuilds:

```bash
git add -A
git commit -m "Describe the change"
git push
```

Because `build.sh` re-runs `migrate` and `seed_studio` every time, a new model
field or a new programme in the seed data needs nothing extra.

### Running a one-off command

**Shell** on the service, then the usual:

```bash
python manage.py createsuperuser
python manage.py seed_studio --demo     # sample data, never on the real studio
python manage.py changepassword director
```

---

## 7. After the first deploy

1. Sign in at `/dashboard/` and change the director password.
2. Remove the `DJANGO_SUPERUSER_*` variables.
3. **Website → Site settings**: real phone numbers, the WhatsApp line, socials,
   opening hours, the sickle cell statement.
4. **Website → Hero slides**: replace the placeholder loop with real footage of
   the studio, and raise *overlay opacity* back to about `0.45` — real video is
   brighter than the placeholder, and the headline needs the contrast.
5. Verify `/healthz` returns `ok`, and that a photo uploaded through the admin
   still loads after you push a trivial change. That last check is the one that
   proves the disk is actually working.

---

## Troubleshooting

**Build fails on `collectstatic`.** Almost always a missing file referenced by
CSS or JS. Note that Django reads `url()` references inside CSS *comments* too —
that is why the optional `@font-face` declarations live in
`static/fonts/README.md` rather than commented out in `brand.css`.

**`ModuleNotFoundError: No module named 'app'`.** The service is running
Render's default `gunicorn app:app` because it was not created from the
blueprint. See section 2b.

**`no such table: ...`, and the traceback mentions `sqlite3`.** `DATABASE_URL`
is not set, so Django fell back to SQLite, and nothing migrated it. Create the
PostgreSQL instance and add `DATABASE_URL` to the web service (Environment →
*Add from database*). Since this is the single most expensive thing to get
wrong, the app now refuses to start in production without it rather than
falling back silently — if you see `ImproperlyConfigured: DATABASE_URL is not
set`, that is this guard doing its job.

**The deploy is marked unhealthy and `/healthz` returns 503 about unapplied
migrations.** The build command is not `./build.sh`, so `migrate` never ran.
See section 2b.

**`DisallowedHost`.** `DJANGO_ALLOWED_HOSTS` does not include the domain you
opened. Add it, including the `www.` variant if you use one.

**CSRF failures on a custom domain.** `DJANGO_CSRF_TRUSTED_ORIGINS` needs the
full origin with the scheme: `https://example.com`, not `example.com`.

**Uploads return 404 after a deploy.** The disk is not mounted, or `MEDIA_ROOT`
does not match its mount path. Both must be `/var/media`.

**Everything is 500 and the log says nothing useful.** Set `DJANGO_DEBUG=true`
briefly to see the traceback, then **turn it off again** — with it on, Django
shows tracebacks and settings to the public.
