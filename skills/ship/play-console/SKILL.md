---
name: play-console
description: Work with Google Play Console for any app on the user's developer account — releases to a track, testers and join links, store listings and settings, app content declarations, form factors, users and permissions, the review lock and sending for review. Use whenever a task touches Play Console or the Play Developer API; Android builds and signing follow `android` and `release`.
---

# Play Console

Two routes, one account. Use the API for everything it covers; drive the console's web UI through
one shared headless WebLua session for the rest.

| Task | Route |
|---|---|
| Upload a bundle to a track, with release notes | `play_api.py upload` |
| Read tracks and releases, a store listing, one-time products | `play_api.py tracks`, `listing`, `products` |
| A store listing's text in one language (add a translation, fix a description) | `play_api.py set-listing` |
| Create a non-consumable one-time product and activate it | `play_api.py product`; console form on an unreviewed app |
| Internal-test join link, testers list | `play_console.py join-link`, `open <pkg> tracks/internal-testing` |
| Whether changes can be sent for review, and sending them | `play_console.py review`, then `click` |
| App content declarations, store settings (category, contact), store listing assets | `play_console.py` |
| Form factors (PC, XR), Android developer verification, users and permissions | `play_console.py` |

## Account and credentials (outside every repo)

- `~/.config/play-console/account.json`: `{"developer": "<account id>", "apps": {"<package>": "<app id>"}}`.
  The ids are in console URLs (`/developers/<id>/app/<id>/`). Add each new app here.
- `~/.config/play-console/service-account.json` (mode 600): the API key of a service account in its
  own Google Cloud project with the Google Play Android Developer API enabled, invited under Users
  and permissions with view app information, app quality, release to testing and production,
  manage testers, manage store presence and policy declarations. Never Admin, never financial data.
  Never print or copy the key; `play_api.py` passes it to openssl through a pipe.
- `~/.local/state/play-console/`: the WebLua session (`WEBLUA_DIR`) whose Chrome profile is signed
  in to the developer account. One session for every project, port 7981.

## API route: `play_api.py`

```sh
play_api.py upload <package> build/android/App.aab --track internal --name "12 (1.2.0)" --notes "What changed."
play_api.py tracks <package>
```

- An upload is one edit: bundle, track releases, commit. Any error discards the edit. Repeat
  `--track` to release it on several tracks in that one edit (`alpha` is closed testing).
- `--status completed` (default) makes the release available to the track's testers; a draft app
  takes it only on internal testing (any other track: `--status draft`, then roll out in the
  console). `--not-for-review` commits without sending changes for review when Play refuses an
  automatic send.
- The version code comes from the bundle; it must be higher than every code already uploaded.
- Verify with `tracks` afterwards; record the version in the project's state doc.
- `product <package> <id> --price 2.49 --title ... --description ...` converts the USD price to every
  region with Play's own rounding, creates the product with one backwards-compatible "buy" option and
  activates it; rerunning updates it. On an app that has never passed review the API answers 403;
  create it in the console instead (`open <pkg> one-time-products`, "Create one-time product",
  option id `buy`, "Set prices" > "Bulk edit pricing", "Select all rows", USD, Apply, Activate) and
  check it with `products`.

## Browser route: `play_console.py`

```sh
play_console.py start                       # headless; status / stop
play_console.py import-cookies <firefox profile dir>   # when the console asks to sign in
play_console.py open <package> app-content/overview
play_console.py text                        # the page as one line, to find what to click
play_console.py click "Save and publish"    # visible button, link, tab or menu item, exact text
play_console.py click "Save and publish" --dialog   # the confirm inside the dialog
play_console.py check "Manage store presence"
play_console.py ctl type 'textarea' '...'   # any weblua-ctl command against the session
```

- Pages: `app-dashboard`, `publishing`, `tracks/internal-testing`, `store-listings`,
  `store-listings/default/edit`, `store-settings`, `app-content/overview`, `advanced-distribution`,
  `monetization-setup`; account pages with `-`: `app-list`, `users-and-permissions`,
  `android-developer-verification`, `policy-center`.
- Read the page (`text`, or a screenshot through `ctl screenshot`) before every click, and again
  after it: the console reports success and errors in the page, not in exit codes.
- Many saves open a second "Save and publish" or "Send" confirm in a dialog. A change is not saved
  until that confirm is clicked; check the page afterwards.
- Material checkboxes hide their input; `check` clicks the visible box and confirms it took. A
  checkbox another permission implies is disabled and stays ticked.
- Store listing saves ask for an AI-content declaration: choose "Don't label assets", then Save.
- Google refuses sign-in inside an automated browser. When a page lands on accounts.google.com
  ("Choose an account", "Signed out"), copy the user's session in from their own Firefox-family
  browser with `import-cookies <profile dir>` (the directory holding `cookies.sqlite`; for Zen under
  Flatpak, `~/.var/app/app.zen_browser.zen/.zen/<profile>/`). It reads a private copy, imports only
  Google's cookies and deletes its files; never print cookie values. If the user is signed out there
  too, ask them to sign in in their browser. Never type their password.

## Review and testers

- Internal testers are an email list on the track's Testers tab. Each tester accepts each app's
  invite once through its join link (`join-link`) before Play lets them install it.
- A new app shows "(unreviewed)" with a temporary name until its first review; internal testing
  works before that.
- `review` reports `locked` (the dashboard has required steps), `ready`, `in review` or `published`.
  "Ready" still needs the user's go-ahead unless they asked for the submission; sending is
  outward-facing.
- A draft app (its dashboard says "Draft app") can only be sent for its first review with a release
  on a reviewed track: closed testing, open testing or production. An internal-testing release does
  not count, and `review` reports `locked` although the dashboard lists nothing left. Fix: on the
  closed track (`closed-testing`, "Manage track") tick the testers list and save, "Add countries /
  regions", "Select all rows", save; put an uploaded version code on track `alpha` with status
  `draft` (the API refuses any other status on a draft app); "Edit release", Next, Save; the
  publishing page then offers "Submit N changes for review".
- A track's testers are either email lists or Google Groups, never both. A group anyone can join
  (groups.google.com; its creation asks the user for a captcha) lets testers sign themselves up;
  the closed test's join link is `https://play.google.com/apps/testing/<package>`.
- Submitting a change while a review is running cancels and restarts that review; save the change
  and send it after the review finishes.
- When `review` still says locked, record what was ruled out in the project's issue; Help > "Create
  support ticket" (App releases > App publishing) shows an AI answer before it files the ticket.
