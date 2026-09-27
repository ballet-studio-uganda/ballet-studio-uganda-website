"""
Clear hero kickers that an early seed froze the founding year into.

The first version of `seed_studio` wrote `Kampala · Since {founded_year}`
straight into `HeroSlide.kicker`. That made the text a snapshot: changing the
founding year in Site settings updated everywhere that reads it live, but left
the hero advertising the old year with no obvious way to tell why.

The template now derives the kicker whenever the field is blank, so emptying
these rows is what puts them back in step.

Deliberately narrow: it only touches values matching the exact phrase the seed
produced. Anything a person typed is left alone -- and if they happened to type
that same phrase, the derived version renders identically, with the right year.
"""

import re

from django.db import migrations

SEEDED = re.compile(r'^\s*Kampala\s*[·.\-]\s*Since\s+\d{4}\s*$', re.IGNORECASE)


def clear_seeded_kickers(apps, schema_editor):
    HeroSlide = apps.get_model('website', 'HeroSlide')
    for slide in HeroSlide.objects.exclude(kicker=''):
        if SEEDED.match(slide.kicker):
            slide.kicker = ''
            slide.save(update_fields=['kicker'])


def noop(apps, schema_editor):
    """
    Irreversible by design.

    Restoring the frozen text would mean guessing which year it held, and the
    derived value is correct anyway -- there is nothing worth putting back.
    """


class Migration(migrations.Migration):

    dependencies = [
        ('website', '0002_founded_year_default'),
    ]

    operations = [
        migrations.RunPython(clear_seeded_kickers, noop),
    ]
