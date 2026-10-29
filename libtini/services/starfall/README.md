# STARFALL rankings

The service runs at `https://appletini.org/leaderboards/starfall`. The page
is plain HTML, so A2LYNX can read it directly. The API below that path has:

- GET `api/run-id`: a fresh 128-bit run ID from the server's random source.
- POST `api/runs`: `run_id`, `name`, `version`, `platform`, `score`, `sector`, `kills`.
- GET `api/ladder`: the ten best player names, one best run per name.

`platform` is required: use `appletini` for the card, `web` for browser play,
or another lowercase slug of 1..24 letters, digits, underscores or hyphens.
It is metadata for the run; the shared table still ranks each name's best
score across platforms. Replies, ladder JSON and the HTML page include it.
Changing platform on a retry of the same run ID returns 409.

The server sets UTC submission time. An identical retry keeps the same run
and time. A changed payload with the same ID returns 409. Names use 1..12
uppercase ASCII letters, digits, spaces, dots, underscores or hyphens.
No game client holds a secret. These are public, unverified scores: limits
and rate checks reduce simple abuse; they do not prove a human played.

The API permits uncredentialed cross-origin GET and JSON POST requests.
OPTIONS answers the browser preflight without a database call. API replies,
including errors, set `Access-Control-Allow-Origin: *`. The HTML page does
not set this header. Deploy this service version before using scores from
an itch.io package. No database migration is needed for this header change.

Limits: 768 request bytes, score 0..9999999, sector 1..256, kills 0..999999,
12 submissions and 120 reads per minute per IP. Rate keys use an IP hash
and expire after a day. No IP is stored with a score. Names are public and
have no accounts or ownership claim. Choose a game name, not personal data.

`worker.mjs` exports `handleStarfall(request, env)`. The site's Worker calls
it before its static-asset handler, and passes its D1 `DB` binding.
`schema.sql` only creates the STARFALL tables and indexes. It does not
change reservation or contact data. Apply it to a local database and test
the Worker before applying the schema and deployment to the public site.

Deployment and real public submissions require their own recorded checks.
Building this service does not publish it. For an older table without the
platform column, apply `migrate_platform.sql` once before deploying this API.
Existing rows get `unknown`; new submissions must specify their platform.
