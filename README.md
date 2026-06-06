<div align="center">

# SuperK

**A Home Assistant add-on repository for a KTX/SRT train reservation helper with a Flask web UI.**

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Add--on-41BDF5?style=for-the-badge&logo=homeassistant&logoColor=white)](https://www.home-assistant.io/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-Web%20UI-000000?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![uv](https://img.shields.io/badge/uv-package%20manager-DE5FE9?style=for-the-badge)](https://docs.astral.sh/uv/)

</div>

---

## Overview

SuperK packages a KTX/SRT train reservation workflow as a **Home Assistant add-on**. The add-on runs a small Flask application inside Home Assistant, exposes a browser-based control panel, reads add-on options from Home Assistant's persistent `/data/options.json`, and writes runtime logs to `/data/superk.log`.

The current add-on focuses on:

- Searching real KTX/SRT trains from the web UI.
- Selecting one or more candidate trains from search results.
- Repeatedly attempting reservations for the selected trains until success or manual stop.
- Optionally sending Telegram notifications for start, success, payment-required, payment-complete, duplicate-reservation, and error events.
- Optionally using saved add-on configuration values as UI presets while keeping sensitive fields blank on the first render.

> **Important:** This project automates interactions with third-party railway reservation systems. Use it responsibly, comply with all applicable service terms, laws, and railway operator policies, and avoid excessive request rates.

---

## Repository Layout

```text
.
├── addons/
│   └── superk/
│       ├── Dockerfile              # Home Assistant add-on container image
│       ├── README.md               # Add-on-specific Korean notes
│       ├── addon.json              # Reference manifest for external tooling
│       ├── config.yaml             # Home Assistant add-on metadata, schema, and defaults
│       ├── requirements.txt        # Runtime Python dependencies for the add-on
│       ├── run.sh                  # Container entrypoint
│       └── src/
│           ├── web_app.py          # Flask UI, API routes, train search, and worker loop
│           └── templates/
│               └── index.html      # Web UI template
├── assets/                         # Application icon assets
├── src/                            # Legacy/desktop Python package scaffolding
├── tests/                          # pytest test suite
├── main.py                         # Legacy PyQt launcher entrypoint
├── pyproject.toml                  # Python project and test/tool configuration
└── repository.yaml                 # Home Assistant add-on repository metadata
```

---

## Features

### Home Assistant Add-on

- Add-on metadata and schema are defined in `addons/superk/config.yaml`.
- The add-on supports `amd64`, `aarch64`, and `armv7` architectures.
- The add-on starts automatically as a Home Assistant service when enabled.
- The Flask UI is exposed through Home Assistant's add-on Web UI configuration.
- The internal default port is `5555`.
- The host port is intentionally **not fixed**; configure the external mapping in Home Assistant's **Network** section.

### Web UI

The Flask UI provides controls for:

- Railway type selection (`ktx` or `srt`).
- Login credentials.
- Optional Korail app-version override for KTX login compatibility.
- Telegram bot token and chat ID.
- Departure station, arrival station, departure date, and departure time.
- Seat preference.
- Adult and child passenger counts.
- Search results and train selection.
- Reservation start/stop controls.
- Live log viewing through the log API.

### Reservation Worker

The internal worker:

- Runs in a background thread.
- Requires selected train numbers before it starts reservation attempts.
- Attempts selected trains one by one.
- Supports required-train semantics for completing multiple required selections.
- Retries after randomized short delays.
- Stops on duplicate-reservation detection.
- Updates status through `/api/status`.

### Logging

- Runtime logs are written to `/data/superk.log` inside the add-on container.
- The log API supports tailing recent lines.
- Reservation-focused filtering hides routine HTTP access log noise.
- Only a single log file is maintained by the add-on runtime.

### Telegram Notifications

When Telegram settings are provided, the worker can send messages for important reservation lifecycle events, including:

- Reservation monitoring start.
- Reservation success.
- Payment required.
- Payment complete.
- Duplicate reservation detection.
- Runtime errors.

### Payment Information

The add-on schema includes optional payment-related fields:

- Card number.
- First two card password digits.
- Corporate-card flag.
- Birth date or business registration number.
- Card expiration date.

If payment information is not provided, the add-on can still attempt reservations and then report that manual payment is required. Treat all payment fields as sensitive data and prefer Home Assistant secrets where possible.

---

## Requirements

### For Home Assistant Users

- A Home Assistant installation that supports add-on repositories.
- Network access from the add-on container to the relevant railway reservation services.
- A KTX/Korail or SRT account, depending on the rail type you use.
- Optional Telegram bot token and chat ID for notifications.

### For Local Development

- Python 3.10 or newer.
- [uv](https://docs.astral.sh/uv/) for convenient dependency management.
- Docker or Home Assistant add-on build tooling if you want to build the add-on container manually.

---

## Installing the Add-on in Home Assistant

1. Open **Home Assistant**.
2. Go to **Settings → Add-ons → Add-on Store**.
3. Open the add-on store menu and choose **Repositories**.
4. Add this repository URL:

   ```text
   https://github.com/jinizest/SuperK
   ```

5. Find **SuperK** in the add-on store.
6. Install the add-on.
7. Open the add-on **Configuration** tab and review the options.
8. Open the **Network** section and map `5555/tcp` to the external port you want to use.
9. Start the add-on.
10. Open the Web UI from the add-on page or browse manually to:

    ```text
    http://<HOME_ASSISTANT_HOST>:<MAPPED_EXTERNAL_PORT>
    ```

---

## Add-on Configuration

The default options are declared in `addons/superk/config.yaml`.

### Top-Level Options

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `log_level` | enum | `info` | Home Assistant add-on log level. |
| `host` | string | `0.0.0.0` | Flask bind address inside the container. |
| `port` | integer | `5555` | Flask port inside the container. |
| `rail_type` | enum | `ktx` | Default railway type: `ktx` or `srt`. |
| `korail_version` | string | `260523001` | Optional Korail app-version value used for KTX login attempts. |

### Login Options

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `login.user_id` | string | empty | KTX/SRT account ID. |
| `login.user_pw` | password | empty | KTX/SRT account password. |
| `login.save_login` | boolean | `false` | UI preference flag for login persistence behavior. |

### Telegram Options

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `telegram.telegram_token` | password | empty | Telegram bot token. |
| `telegram.telegram_chat_id` | string | empty | Telegram chat ID that receives notifications. |
| `telegram.save_telegram` | boolean | `false` | UI preference flag for Telegram persistence behavior. |

### Search Options

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `search.departure` | string | `서대구` | Default departure station. |
| `search.arrival` | string | `행신` | Default arrival station. |
| `search.departure_date` | string | empty | Date in `YYYYMMDD` or another UI-supported date format. Empty means the app can fall back to the current date. |
| `search.departure_time` | string | `0700` | Earliest departure time, normalized to `HHMM`. |
| `search.seat_preference` | enum | `general_first` | Seat selection strategy. |
| `search.adult` | integer | `1` | Adult passenger count. |
| `search.child` | integer | `0` | Child passenger count. |
| `search.path_index` | integer | `0` | Optional route/path index for service-specific search results. |

Supported `seat_preference` values:

- `general_first`: Prefer standard/general seats, but allow special seats if needed.
- `special_first`: Prefer special/first-class seats, but allow general seats if needed.
- `general_only`: Only attempt standard/general seats.
- `special_only`: Only attempt special/first-class seats.

### Payment Options

| Option | Type | Default | Description |
| --- | --- | --- | --- |
| `payment.card_number` | password | empty | Payment card number. |
| `payment.card_password_2` | password | empty | First two digits of the card password. |
| `payment.is_corporate_card` | boolean | `false` | Whether the payment card is corporate. |
| `payment.birth_date` | password | empty | Birth date or business registration number, depending on card type. |
| `payment.card_expire` | password | empty | Card expiration value. |
| `payment.save_payment` | boolean | `false` | UI preference flag for payment persistence behavior. |

---

## Web UI Workflow

### 1. Configure Presets

Set default values in the add-on **Configuration** tab. These values are stored by Home Assistant under `/data/options.json` and loaded by the Flask app at startup/request time.

Sensitive fields are treated carefully in the UI: the initial page render uses blank waiting values for sensitive input fields, while saved configuration can be used as presets.

### 2. Open the Web UI

Use the add-on Web UI button or manually browse to the host/port mapping configured for `5555/tcp`.

If you changed the internal `port` option away from `5555`, make sure the Home Assistant Web UI mapping and `config.yaml` port definitions match. Otherwise, the add-on Web UI button can open the wrong URL.

### 3. Search for Trains

Enter or confirm:

- Rail type.
- Login credentials.
- Departure station.
- Arrival station.
- Departure date.
- Departure time.
- Passenger counts.
- Seat preference.

Then run the train search. Search failures are returned by `/api/search` and displayed by the UI.

### 4. Select Trains

Choose one or more trains from the search results. The reservation worker requires selected train numbers; if no train is selected, it stops immediately and logs that no selected trains were provided.

### 5. Start Reservation Monitoring

Start the worker from the UI. The worker will attempt selected trains repeatedly until:

- A reservation succeeds.
- All required train selections are completed.
- A duplicate reservation condition is detected.
- An error forces a stop.
- You manually stop the worker.

### 6. Watch Logs and Status

Use the web UI logs panel or API endpoints to monitor progress. Reservation-related lines can be filtered through the log API.

---

## API Reference

The Flask application exposes the following routes.

| Method | Route | Description |
| --- | --- | --- |
| `GET` | `/` | Render the main web UI. |
| `POST` | `/start` | Legacy form endpoint that starts the worker with a basic payload. |
| `POST` | `/stop` | Legacy form endpoint that stops the worker. |
| `POST` | `/api/search` | Search real trains using the submitted JSON payload. |
| `POST` | `/api/run/start` | Start the reservation worker with selected train JSON payload. |
| `POST` | `/api/run/stop` | Stop the reservation worker. |
| `GET` | `/api/status` | Return current worker status. |
| `GET` | `/api/logs` | Return recent log lines. Supports query parameters documented below. |

### `GET /api/logs` Query Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `tail` | `200` | Number of recent lines to return. Clamped between `1` and `1000`. |
| `reservation_only` | `0` | When non-zero, returns only reservation-related log lines. |

Example:

```bash
curl 'http://<HOST>:<PORT>/api/logs?tail=100&reservation_only=1'
```

---

## Running Locally for Development

### Install Dependencies

```bash
uv sync --extra dev
```

If you only need the add-on Flask runtime dependencies, install from the add-on requirements file:

```bash
uv pip install -r addons/superk/requirements.txt
```

### Run the Flask Add-on App Locally

The app expects Home Assistant-style runtime data under `/data`. For local testing, create the directory if needed:

```bash
sudo mkdir -p /data
sudo chown "$USER" /data
```

Then run:

```bash
uv run python addons/superk/src/web_app.py
```

Open:

```text
http://127.0.0.1:5555
```

### Run Tests

```bash
uv run pytest
```

The test configuration is declared in `pyproject.toml` and includes coverage reporting for the `src` package.

---

## Building the Add-on Container Manually

From the add-on directory:

```bash
cd addons/superk
docker build -t superk-addon .
```

Run a quick local container test with a writable data directory:

```bash
docker run --rm \
  -p 5555:5555 \
  -v "$(pwd)/../../.local-data:/data" \
  superk-addon
```

Then open:

```text
http://127.0.0.1:5555
```

> The official Home Assistant add-on build process may inject a different `BUILD_FROM` base image for each target architecture.

---

## Troubleshooting

### Web UI opens `about:blank#blocked` or a blank page

- Confirm that `5555/tcp` is mapped in the Home Assistant add-on **Network** section.
- If the add-on's internal `port` option was changed, update the Web UI/port mapping accordingly or browse manually to the mapped external port.
- Avoid mapping the same host port to multiple services.

### Port conflict

The add-on does not reserve a fixed host port by default. Keep the internal port as `5555` unless you know you need to change it, and choose an unused external port in Home Assistant's Network settings.

### KTX login fails with a latest-version or app-version error

Korail may reject outdated app-version identifiers. The add-on has a `korail_version` option that can be used to provide a newer version string. The default value is declared in `addons/superk/config.yaml`.

### Train search says login credentials are required

Provide the correct account ID and password either in the UI or in the add-on configuration under `login.user_id` and `login.user_pw`.

### No reservation attempts start

Select at least one train from the search results before starting the worker. The worker intentionally stops if it receives no selected train numbers.

### Logs are noisy

Use the reservation-only filter in the UI or call:

```bash
curl 'http://<HOST>:<PORT>/api/logs?reservation_only=1'
```

---

## Security Notes

- Home Assistant stores add-on options in its add-on data area; sensitive schema fields are marked as `password` where supported.
- Avoid committing real credentials, card details, Telegram tokens, or chat IDs.
- Prefer Home Assistant secrets for sensitive values.
- Restrict network access to the Web UI to trusted users only.
- Review logs before sharing them because they may include operational details.

---

## Development Notes

- The add-on runtime entrypoint is `addons/superk/run.sh`.
- The Flask app is implemented in `addons/superk/src/web_app.py`.
- UI markup is in `addons/superk/src/templates/index.html`.
- Tests for the add-on web app are in `tests/unit/test_addon_web_app.py`.
- Python test, coverage, formatting, linting, and typing configuration is in `pyproject.toml`.

Recommended development loop:

```bash
uv run pytest
uv run ruff check .
uv run black --check .
```

---

## Contributing

1. Create a topic branch.
2. Make focused changes.
3. Add or update tests when behavior changes.
4. Run the relevant checks.
5. Keep credentials and runtime data out of commits.
6. Open a pull request with a clear summary and testing notes.

---

## Disclaimer

SuperK is provided as a reservation helper and automation wrapper. It is not affiliated with, endorsed by, or operated by Korail, SR, Home Assistant, or any railway operator. Reservation availability, login behavior, payment behavior, and API compatibility can change without notice. You are responsible for how you configure and use this software.
