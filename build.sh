#!/usr/bin/env bash
# Render build step for Ballet Dance Studio UG.
#
# Runs on every deploy, so each step has to be safe to repeat:
#   collectstatic  overwrites
#   migrate        no-ops when there is nothing new
#   seed_studio    is get_or_create throughout
#   createsuperuser only runs when the env vars are set AND no user exists

set -o errexit          # stop on the first failure
set -o pipefail
set -o nounset

echo "--> Installing dependencies"
pip install --upgrade pip
pip install -r requirements.txt

echo "--> Collecting static files"
python manage.py collectstatic --no-input

echo "--> Applying migrations"
python manage.py migrate --no-input

echo "--> Seeding reference data"
# Programmes, terms, the skill rubric, fee and expense categories, and the
# hero placeholder. Safe against a live database -- it only fills in gaps.
python manage.py seed_studio

# Create the first login without anyone having to open a shell. Django's
# --no-input createsuperuser reads DJANGO_SUPERUSER_* from the environment, and
# needs the email as well as the username and password, because email is a
# required field on this project's user model.
if [[ -n "${DJANGO_SUPERUSER_USERNAME:-}" \
   && -n "${DJANGO_SUPERUSER_EMAIL:-}" \
   && -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]]; then
  echo "--> Ensuring the director account exists"
  python manage.py createsuperuser --no-input || \
    echo "    (already exists - leaving it alone)"
elif [[ -n "${DJANGO_SUPERUSER_USERNAME:-}" ]]; then
  echo "--> DJANGO_SUPERUSER_USERNAME is set but EMAIL and/or PASSWORD are not;"
  echo "    skipping. Set all three, or create the account from the shell."
fi

echo "--> Build complete"
