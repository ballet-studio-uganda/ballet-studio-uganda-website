# Brand fonts

The Ballet Dance Studio UG manual specifies two licensed typefaces that cannot
be redistributed and are not on any web-font CDN:

| Role                | Brand font             | Stand-in used until you add it |
|---------------------|------------------------|--------------------------------|
| Script / wordmark   | Adinda Melia Regular   | Italianno                      |
| Logotype caps       | Bank Gothic Medium BT  | Michroma                       |
| Body text           | Montserrat             | Montserrat (already loaded)    |

## To use the real fonts

1. Convert each to `.woff2` (and optionally `.woff`) — e.g. with
   <https://transfonter.org>.
2. Drop them here with these exact names:
   - `AdindaMelia.woff2` / `AdindaMelia.woff`
   - `BankGothicMediumBT.woff2` / `BankGothicMediumBT.woff`
3. Paste these two declarations at the top of `static/css/brand.css`,
   just above the `:root` block:

   ```css
   @font-face {
     font-family: 'Adinda Melia';
     src: url('../fonts/AdindaMelia.woff2') format('woff2'),
          url('../fonts/AdindaMelia.woff') format('woff');
     font-weight: 400;
     font-display: swap;
   }

   @font-face {
     font-family: 'Bank Gothic Medium BT';
     src: url('../fonts/BankGothicMediumBT.woff2') format('woff2'),
          url('../fonts/BankGothicMediumBT.woff') format('woff');
     font-weight: 500;
     font-display: swap;
   }
   ```

   They are kept here rather than commented out in the stylesheet because
   `collectstatic` reads `url()` references inside CSS comments as well, and
   fails the production build when the files are missing.

Nothing else needs to change — `--font-script` and `--font-logo` already list
the brand faces first and fall through to the stand-ins.
