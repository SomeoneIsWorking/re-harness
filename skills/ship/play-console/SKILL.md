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

- An upload is one edit: bundle, track release, commit. Any error discards the edit.
- `--status completed` (default) makes the release available to the track's testers, even on a
  draft app. `--not-for-review` commits without sending changes for review when Play refuses an
  automatic send.
- The version code comes from the bundle; it must be higher than every code already uploaded.
- Verify with `tracks` afterwards; record the version in the project's state doc.

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
- When `review` says locked but the dashboard shows nothing left to do, record what was ruled out
  in the project's issue rather than guessing; Play Console Help's contact form is the last step.
