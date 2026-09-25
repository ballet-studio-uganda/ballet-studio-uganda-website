"""Static file storage."""

from whitenoise.storage import CompressedManifestStaticFilesStorage


class ForgivingManifestStaticFilesStorage(CompressedManifestStaticFilesStorage):
    """
    Manifest static storage that does not die over a third-party source map.

    Minified vendor bundles routinely end with a `sourceMappingURL` comment
    pointing at a `.map` file the package never ships -- django-jazzmin's
    copy of Bootstrap is one. Django's manifest storage treats every missing
    reference as fatal, so a stock `collectstatic` fails the whole build over a
    debugging aid that no browser will ever ask for in production.

    Missing files in *our own* CSS and JS are still worth knowing about, so
    those are reported rather than silently dropped.
    """

    #: Serve a file even when it is absent from the manifest, instead of
    #: raising at request time.
    manifest_strict = False

    #: References we are content to leave unresolved.
    IGNORED_SUFFIXES = ('.map',)

    def post_process(self, paths, dry_run=False, **options):
        for name, hashed_name, processed in super().post_process(
            paths, dry_run, **options
        ):
            if isinstance(processed, Exception) and self._is_ignorable(processed):
                # Keep the file, drop the complaint about its source map.
                processed = False
            yield name, hashed_name, processed

    def _is_ignorable(self, error):
        message = str(error)
        return (
            'could not be found' in message
            and any(message.rstrip(":' \n").endswith(s) or s in message
                    for s in self.IGNORED_SUFFIXES)
        )
