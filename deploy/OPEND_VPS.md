> **Do you actually need OpenD on the server?** If the host cannot run a signed-in
> gateway (shared hosting, no GUI, no credentials on a third-party box), set
> `DATA_SOURCE=yahoo` and the demo runs on Yahoo Finance over HTTPS instead: same
> pages, no account, prices possibly delayed. Everything below applies only if you
> want *your* real-time moomoo entitlement on that machine.

# Running OpenD on a VPS, and why the demo may still differ

OpenD is a gateway, not a desktop-only app: moomoo ships CentOS and Ubuntu builds for exactly
this case. If the site is hosted, the gateway has to live next to it (or be reachable over TCP).

Source: <https://openapi.moomoo.com/moomoo-api-doc/en/opend/opend-cmd.html>

## 1. The binary is a Linux CLI, and it needs a logged-in account

```bash
# on the VPS
mkdir -p /opt/opend && cd /opt/opend
# download the Command Line OpenD for CentOS/Ubuntu from the moomoo OpenAPI page, then:
unzip OpenD*.zip && chmod +x FutuOpenD

# first run: interactive, asks for account, password, "remember?"
./FutuOpenD -lang=en
```

After a successful interactive login with "remember password" it can start unattended:

```bash
./FutuOpenD -login_account=<your-id> -login_by_remember=1 -lang=en
```

The first login from a new machine also requires completing the **API Questionnaire and
Agreements** in the moomoo app before calls are accepted.

`FutuOpenD.xml` holds the rest (port, log level, `login_account`). The default quote port is
**11111**, which is what this app expects.

## 2. The login IP decides your data tier

From moomoo's own permissions page: whether an account counts as a *domestic certified* or
*international* customer is decided **by the IP address OpenD logs in from**.

Consequence: a VPS in Singapore/Frankfurt/US is not "your laptop in Malaysia". The same
account can receive a *different* quote tier there — different delay, different order-book
depth, and different products available for free. If US quotes worked locally and look absent
or delayed on the VPS, this is the first thing to check, before assuming a code fault.

## 3. One session per account

Logging OpenD in on the VPS typically logs the desktop one out (or is refused). Plan for the
gateway to live in one place:

- VPS only → run it there permanently, your desktop loses the connection.
- Desktop only → the hosted site has no market data (this is the current state).
- Neither is "both at once".

## 4. Public display is a licensing question, not a technical one

Quote entitlements are granted for *your* use of the data. Publishing real-time exchange data
on a public website that anyone can open is redistribution, and the standard moomoo/Futu
entitlement does not grant it. This applies regardless of where OpenD runs — a VPS just makes
it easier to do accidentally.

For a coursework demo the defensible options are:

1. **No live quotes on the public host** (what the app does now: "OpenD is not listening",
   news and the journal still work). Nothing to license, nothing to leak.
2. **Run it on your own machine** and demo from there, with the public host as a static showcase.
3. Ask the moomoo account manager in writing before publishing real-time data.

## Supervising it (systemd)

```ini
# /etc/systemd/system/opend.service
[Unit]
Description=moomoo OpenD gateway
After=network-online.target

[Service]
WorkingDirectory=/opt/opend
ExecStart=/opt/opend/FutuOpenD -login_account=YOUR_ID -login_by_remember=1 -lang=en
Restart=always
RestartSec=10
User=opend

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now opend
journalctl -u opend -f          # the login result and any quota errors land here
```

Restart-on-failure matters: the gateway drops on network blips and session expiry, and a
dropped gateway looks exactly like "the app has no data".

## Pointing the app at it

Same machine (normal):

```
OPEND_HOST=127.0.0.1
OPEND_PORT=11111
OPEND_TRADE_MARKET=US
```

OpenD on another box: bind it in `FutuOpenD.xml` (`<ip>0.0.0.0</ip>`), firewall the port to the
app server only, and set `OPEND_HOST` to that address. Never expose 11111 to the internet —
it is an authenticated gateway to a brokerage account.

## Check it before blaming the site

```bash
./.venv/bin/python -m scripts.check_opend --symbol US.AAPL
```

Five PASS/FAIL layers: SDK present, port open, OpenD answers, quote returned, positions read.
The first failing line is the answer.
