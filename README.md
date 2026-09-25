# Ballet Dance Studio UG

> **Resilience. Hope. Dreams.**

The studio's public website and its management system, in one Django project.
Visitors see a video-led marketing site; staff, parents and dancers sign in to
the same domain and get the dashboard built for their role.

---

## Getting started

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_studio --demo
python manage.py createsuperuser
python manage.py runserver
```

Then open <http://localhost:8000>. The dashboard is at `/dashboard/`.

`seed_studio` without `--demo` creates only the reference data a real studio
needs on day one — programmes, terms, the skill rubric, fee and expense
categories. It is safe to run against a live database; everything is
`get_or_create`. Add `--demo` for sample dancers, classes, attendance,
invoices and a recital to click through. Demo accounts use the password
`studio2026`.

```bash
python manage.py test          # 82 tests, ~3 seconds
```

---

## What it does

### For visitors
A full-bleed **video hero** sits directly beneath the navigation with the
headline animating in word by word (the reference was [abt.org](https://www.abt.org/)).
Below it: programmes, the December recital, the events calendar, news,
photo galleries, testimonials and faculty. Everything on the page is editable
by an administrator — nothing is hard-coded into a template.

The **annual recital** has a page of its own at `/events/recital/`, with its own
video hero, a live countdown, the programme of works with cast lists, ticket
prices, a fundraising thermometer and the studio's sickle cell awareness
message. Past years live at `/events/recital/<year>/`.

### For the studio

| Role | Sees |
|---|---|
| **Creative Director / Administrator** | Everything: finances, people, verification queue, all classes and dancers |
| **Teacher** | Their own classes, registers, dancers and progress reports |
| **Parent / Guardian** | Their own children's attendance, reports and fee statement |
| **Student** | Their own timetable, attendance and progress |

**Money.** Payments are recorded by hand, as the studio actually takes them —
cash, MTN Mobile Money, Airtel Money, bank deposit or transfer, cheque, card.
Each record carries the date *and time* on the SMS or slip, the transaction ID,
who paid, who received it and who typed it in, plus an optional photo of the
receipt. A transaction ID is **required** for every method where one exists, and
the same reference cannot be banked twice. Invoices recalculate themselves,
bursaries apply automatically, and reversals restore the balance.

The reports page renders the same aggregation over any period — week, month,
quarter, year, rolling windows, or a custom range — as income-vs-expense trend,
income sources, expense categories, payment-method mix, revenue by programme and
a debt-ageing analysis. Payments and expenses export to CSV for the accountant.

**Attendance.** One tap marks the whole class present, then you correct the
exceptions. Re-saving a register updates it rather than duplicating it. Dancers
whose attendance drops below 70% surface on the dashboard so someone rings the
family before a child quietly stops coming.

**Progress.** Teachers score a rubric of named skills (grouped into Technique,
Musicality, Artistry, Physical development, Discipline) and write to the family
rather than to a file. Reports go draft → submitted → published; a family only
ever sees a published one. Scores over time become the dancer's progress chart.

---

## Layout

```
apps/
  accounts/    User, roles, verification, staff/guardian/student profiles,
               permissions, notifications, audit log
  academics/   Years, terms, programmes, classes, timetable, enrolment,
               sessions, attendance, the skill rubric, progress reports
  finance/     Fees, bursaries, invoices, payments, expenses, other income,
               payroll, budgets, and the reporting engine
  events/      Event calendar, registrations, the annual recital, cast lists,
               rehearsals, partners
  website/     Site settings, hero slides, news, announcements, galleries,
               testimonials, FAQs, flat pages, contact inbox
templates/     base.html (public) and dashboard/base.html (management)
static/css/    brand.css (design system) · site.css (public) · dashboard.css
static/js/     site.js (hero, reveal, lightbox) · dashboard.js (charts, register)
```

Business logic that is more than a line or two lives in `services.py`
(`apps/finance/services.py`, `apps/academics/services.py`) rather than in views,
so the same aggregation backs the page, the JSON endpoint and the tests.

---

## Brand

From the manual:

| | |
|---|---|
| Colours | `#EE2A7B` pink · `#701344` plum |
| Script / wordmark | Adinda Melia Regular |
| Logotype caps | Bank Gothic Medium BT |
| Body | Montserrat |

Both licensed faces are stood in for until you supply the files — Italianno for
the script and Michroma for the squared caps. See `static/fonts/README.md`;
it is a two-minute job to swap them in.

Everything else is a CSS custom property at the top of `static/css/brand.css`.
Change a colour there and it changes everywhere, charts included.

---

## Things to do before going live

1. **Set the environment.** Nothing sensitive is hard-coded, but the defaults
   are development ones:

   ```bash
   DJANGO_SECRET_KEY=<a new random 50-char string>
   DJANGO_DEBUG=false
   DJANGO_ALLOWED_HOSTS=balletdancestudioug.com,www.balletdancestudioug.com
   DJANGO_CSRF_TRUSTED_ORIGINS=https://balletdancestudioug.com
   DATABASE_URL=postgres://user:password@host:5432/dbname
   EMAIL_HOST=…  EMAIL_HOST_USER=…  EMAIL_HOST_PASSWORD=…
   ```

   With `DJANGO_DEBUG=false` the project turns on HTTPS redirects, HSTS, secure
   cookies and the rest by itself. `psycopg` is already installed — Postgres
   needs only `DATABASE_URL`.

2. **Serve static and media files.** Run `collectstatic` and put a real web
   server or object store in front of `/static/` and `/media/`. Django's dev
   server will not do it.

3. **Replace the hero video.** A generated placeholder is in place —
   an abstract loop of drifting stage light in the brand palette, at
   `media/site/hero/hero-placeholder.mp4`. Swap it for real footage of the
   studio under Admin → Website → Hero slides: a muted MP4 of roughly 10–25
   seconds, under about 15 MB, with a poster image for the moment before it
   loads. Real footage is usually brighter than the placeholder, so raise
   *overlay opacity* back to around `0.45` when you do, to keep the headline
   readable. With no video at all the page falls back to a styled gradient
   rather than a blank rectangle.

   The placeholder was produced by a throwaway script, not by anything the
   project depends on — `imageio`/`imageio-ffmpeg` are **not** in
   `requirements.txt` and nothing at runtime needs them.

4. **Fill in Site settings.** Admin → Website → Site settings: real phone
   numbers, the WhatsApp line, social links, opening hours, and the studio's
   sickle cell statement.

5. **Check the health fields.** `Student` records can hold sickle cell status,
   allergies, medication and doctor details. They default to *not disclosed* and
   are visible only to teaching staff — but they are personal data, so confirm
   the studio's consent wording before collecting them.

---

## Notes for whoever picks this up next

- **Students are not users.** A three-year-old in Kinder Ballet is a real
  student long before anyone gives them a password, so `Student.user` is
  optional and names live on the student record, not the account.
- **Nothing is deleted.** Payments reverse, invoices are written off, dancers
  are marked withdrawn. The `AuditLog` records who changed what.
- **`{% static_v %}`, not `{% static %}`**, for CSS and JS — it stamps the URL
  with the file's mtime so an edit lands without a hard refresh.
- **Adding a new dashboard page**: extend `dashboard/base.html`, add the route
  to the right app's `urls.py`, and add a `nav-item` to
  `templates/dashboard/includes/sidebar.html` scoped by
  `request.resolver_match.namespace` (unscoped matches highlight two items at
  once — that bug has been fixed once already).
