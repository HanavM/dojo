# pay.sh CLI — setup + usage notes

Verified on macOS (Apple Silicon), 2026-09-30, against `pay` **0.29.0**.
Docs entry point: <https://pay.sh/docs/llms.txt> (every page is also available as
`https://pay.sh/docs/<slug>/index.md`).

---

## 1. Install + auth (exact commands that worked)

```sh
brew install pay          # /opt/homebrew — installed pay 0.29.0
pay --version             # -> pay 0.29.0
```

Wallet creation + redeem, in one step:

```sh
pay setup --backend keychain --redeem 81K6T2ASZS
```

Result:

```
Activation complete
Account `hanavmodasiya` (6Gfh…ZNjw) funded 🎉 $5
```

Notes on this command:

* `--backend keychain` is **required** in a non-interactive shell. Without it the
  command dies with `Configuration error: No --backend specified and no
  interactive terminal available.` Valid backends: `keychain`, `connect`,
  `payconnect`, `openfort`, `privy`, `ledger`.
* `--redeem <CODE>` is on `pay setup`, **not** a top-level `pay redeem` command.
  It skips the MoonPay/onramp TUI and has the pay-api gateway fund the account
  from its hot wallet. It reuses an existing account if one is already present.
* Side effect: `pay setup` also installed the pay MCP server into Claude Code,
  Claude Desktop and Codex configs. Use `pay setup --update` to re-emit those
  without creating a new account.

### Current wallet

| | |
|---|---|
| Account name | `hanavmodasiya` |
| Network | mainnet |
| Address | `6GfhRQaXwEd8WoQCkQDLRYxSpdz7EFYcLiV87QSXZNjw` |
| Balance | **5.00 USDC** (after redeeming the code) |
| Key storage | Apple Keychain (`keystore: apple-keychain`, `auth_required: true`) |
| Account index | `~/.config/pay/accounts.yml` (pubkey only — no secret material) |

The secret key never leaves the macOS Keychain. It is not in `accounts.yml` and
is not recorded anywhere in this repo. `pay account export` would write it to
disk — do not run it.

Verify anytime:

```sh
pay whoami          # user, active mainnet account, non-zero stablecoin balances
pay account list
```

---

## 2. Sandbox / test mode — yes

`--sandbox` (alias `--dev`, short `-s`) is a full test network. It routes to a
hosted Surfpool localnet at `https://402.surfnet.dev:8899` and **auto-funds an
ephemeral wallet on first use**, so no real funds move and no account is needed.

```sh
pay --sandbox curl https://debugger.pay.sh/mpp/quote/AAPL   # first paid call, zero setup
```

Network flags (mutually exclusive, and they go **before** the subcommand):

| Flag | Network | RPC |
|---|---|---|
| `--sandbox` / `-s` | hosted Surfpool localnet | `https://402.surfnet.dev:8899` |
| `--local` | your own Surfpool | `http://localhost:8899` |
| `--mainnet` | mainnet (real money) | `https://api.mainnet-beta.solana.com` |
| *(none)* | read from the 402 challenge advertisement | — |

`devnet` also exists as an `operator.network` value in a paywall spec, but the
CLI's own test path is `--sandbox`. Rule of thumb from the docs: use `--sandbox`
for everything except deliberate real spend.

---

## 3. Putting a paywall in front of an existing HTTP server

The gateway is a reverse proxy. Point `routing.url` at your existing server and
run:

```sh
pay --sandbox gate api paywall.yml --bind 127.0.0.1:1402     # test
pay gate api paywall.yml --bind 0.0.0.0:8080                 # mainnet
```

* `pay gate api` replaces the older `pay server start` / `pay serve start`.
* It is also the canonical validator — a bad spec prints `Configuration error`
  and the gateway refuses to start.
* `--sandbox` also launches the Payment Debugger UI at the bind address; on
  mainnet add `--debugger` if you want it.
* Scaffold a starter file with `pay server scaffold paywall.yml`.
* `endpoints[]` is an **allowlist** — anything not listed is not reachable
  through the gateway even if the upstream serves it.

### Minimal working `paywall.yml` (verified running)

```yaml
# yaml-language-server: $schema=https://pay.sh/docs-assets/provider.schema.json
name: trainme-demo
subdomain: trainme-demo
title: 'TrainMe Demo API'
description: 'Paywalled demo in front of a local HTTP server.'
category: ai_ml          # ai_ml|cloud|compute|data|devtools|finance|identity|maps|
                         # media|messaging|productivity|search|security|shopping|
                         # storage|translation|other
version: v1

routing:
  type: proxy                     # or `respond` to 200 immediately, no upstream
  url: http://127.0.0.1:9000/     # your existing server
  # auth:                         # optional: inject upstream creds AFTER payment
  #   method: query_param
  #   key: 'api-key'
  #   value_from_env: UPSTREAM_API_KEY

operator:
  currencies:
    usd: ['USDC']
  network: localnet               # sandbox forces localnet; use `mainnet` in prod
  fee_payer: true                 # operator sponsors SOL fees for callers
  # recipient: '<revenue-wallet>' # defaults to the active account's pubkey
  # signer: { backend: file, path: '/etc/pay/keypair.json' }

endpoints:
  - method: GET
    path: 'health'                # no metering/subscription block => FREE
    description: 'Health check (free).'

  - method: GET
    path: 'cheap'
    description: 'Cheap paid call.'
    metering:
      dimensions:
        - direction: usage        # usage | input | output
          unit: requests          # requests | tokens | characters | pages | bytes | …
          scale: 1                # units covered by each price_usd
          tiers:
            - price_usd: 0.001

  - method: GET
    path: 'expensive'
    description: 'Expensive paid call.'
    metering:
      dimensions:
        - direction: usage
          unit: requests
          scale: 1
          tiers:
            - price_usd: 0.05
```

Gateway startup printed exactly:

```
3 endpoints (2 metered, 1 free)
GET  health      free
GET  cheap     $0.001
GET  expensive  $0.05
```

Other useful top-level blocks: `free_tier` (N free requests before metering),
`quotas` (rate limits independent of payment), `recipients` + `splits` (revenue
splits), `env`, `accounting: pooled | per_agent`, `session` (see below).

Full field reference: `pay docs schema > provider.schema.json`, or
<https://pay.sh/docs-assets/provider.schema.json>.

---

## 4. How a CLIENT pays

### CLI (simplest, handles wallet + signing + retry)

```sh
pay --sandbox curl http://127.0.0.1:1402/cheap
pay --sandbox curl https://gw.example.com/v1/search \
  -H 'content-type: application/json' -d '{"query":"test"}'
```

Everything after `curl` is forwarded verbatim to the system `curl`. Also
available: `pay wget`, `pay http` (HTTPie), and `pay fetch` (built-in client, no
external binary needed).

Unpaid vs paid, observed:

```
$ curl -i http://127.0.0.1:1402/cheap
HTTP/1.1 402 Payment Required
www-authenticate: Payment id="…", realm="…", method="solana", intent="charge", request="<base64>"
{"error":"payment_required","payment":{"schemes":["mpp/charge"]},
 "pricing":{"dimensions":[{"direction":"usage","price_usd":0.001,"scale":1,"unit":"requests"}]}}

$ pay --sandbox curl -i http://127.0.0.1:1402/cheap
HTTP/1.0 200 OK
payment-receipt-url: https://pay.sh/receipt/<sig>?network=sandbox
payment-receipt: <base64 JSON: challengeId, method, reference, status, timestamp>
{"ok":true,"route":"cheap"}
```

### Python SDK (paying side, x402)

```python
from solana_pay_kit import Signer
from solana_pay_kit.protocols.x402.client import SolanaRpc, x402_async_client

# returns an httpx.AsyncClient that turns any 402 into a signed
# PAYMENT-SIGNATURE and replays the request transparently
async with x402_async_client(signer, rpc) as http:
    resp = await http.get("https://api.example.com/quote")
    print(resp.status_code, resp.headers.get("payment-response"))
```

Low-level, if you drive your own HTTP:

```python
from solana_pay_kit.protocols.x402.client import build_payment_header, parse_x402_challenge

offer  = parse_x402_challenge(headers, body, selection)
header = await build_payment_header(signer, rpc, offer)   # base64 PAYMENT-SIGNATURE
```

Install: `pip install "solana-pay-kit[fastapi]"` (or `[flask]` / `[django]`).
Signers: `Signer.file("operator.json")`, `Signer.env("OPERATOR_KEY")`,
`Signer.demo()` (non-mainnet only — raises `DemoSignerOnMainnetError` on mainnet).

---

## 5. Paid session: one payment, later requests free

The receipt itself is **not** a bearer token you re-attach by hand. pay caches a
SIWMPP session token / on-chain delegation per `realm` and replays it for you.
Two mechanisms:

### A. `subscription:` — pay once, free for the period (VERIFIED WORKING)

```yaml
operator:
  currencies: { usd: ['USDC'] }
  network: localnet
  fee_payer: true
  realm: 'trainme-demo2'                 # REQUIRED for subscriptions
  challenge_binding_secret: '<64 hex>'   # REQUIRED; openssl rand -hex 32

endpoints:
  - method: GET
    path: 'quote/{symbol}'               # per-call, charged every time
    metering:
      dimensions:
        - { direction: usage, unit: requests, scale: 1, tiers: [{ price_usd: 0.01 }] }

  - method: GET
    path: 'pro'                          # flat fee, then free for 30 days
    subscription:
      period: '30d'
      price_usd: 1.00
      currency: USDC
```

```sh
pay --sandbox curl http://127.0.0.1:1403/pro    # 1st call: activates, pays $1.00
pay --sandbox curl http://127.0.0.1:1403/pro    # later calls: free, ~0.6s, no new charge
```

The activation response carries:

```
payment-receipt: <base64 JSON with subscriptionId, subscriptionDelegation,
                  periodStart, periodEnd, reference, status>
```

pay stores that delegation locally and re-attaches it automatically — you do not
pass anything on follow-up requests. Inspect / manage:

```sh
pay subscriptions list            # --json for scripting, --network mainnet to filter
pay subscriptions status <SUBSCRIPTION_ID>
pay subscriptions cancel <SUBSCRIPTION_ID>     # moves nothing extra, but is high-intent
```

Every endpoint carrying a `subscription:` block with the same plan is covered by
that one activation — that is the "second endpoint is free within the same paid
session" pattern.

Caveat: `metering:` and `subscription:` are mutually exclusive on a single
endpoint (v0 design). A route is either per-call or subscription, not both.

### B. `session:` — MPP payment channel (issues challenges, but see gotcha)

```yaml
session:
  cap_usdc: 1.0            # deposit ceiling
  close_delay_ms: 60000    # idle delay before settle+close; 0 disables auto-close

endpoints:
  - method: GET
    path: 'stream'
    metering:
      schemes: [mpp-session]
      dimensions:
        - { direction: usage, unit: requests, scale: 1, tiers: [{ price_usd: 0.0001 }] }
```

Wire protocol: the client opens a channel once
(`Authorization: Payment` with `action: "open"`), then each follow-up carries
`action: "voucher"` with a **cumulative** total; the gateway serves off-chain and
settles once when the channel idles. `Payment-Receipt` returns
`acceptedCumulative`, `spent`, and on close `refunded` + settlement `txHash`.

Free-tier alternative: a top-level `free_tier: { amount, unit, period }` block
serves N requests free before metering kicks in.

---

## 6. Gotchas found the hard way

* **`--backend` is mandatory non-interactively.** `pay setup` without it fails
  with `No --backend specified and no interactive terminal available`.
* **Redeem lives on `setup`**, not a `pay redeem` subcommand:
  `pay setup --backend keychain --redeem <CODE>`.
* **Global flags go before the subcommand.** `pay --sandbox curl <url>`, not
  `pay curl --sandbox <url>`.
* **Subscriptions need two extra `operator:` fields** or the gateway refuses to
  boot: `realm` and `challenge_binding_secret` (`openssl rand -hex 32`). The
  secret must be **stable across restarts** — rotating it invalidates every
  outstanding SIWMPP session token. In production set it from the environment:
  `challenge_binding_secret: '${PAY_MPP_CHALLENGE_SECRET}'`. Keep the real value
  in a secret store, never in a committed YAML.
* **Subscription plans need a TTY on first launch.** The gateway prompts
  `Publish create_plan on-chain now? (costs ~0.001 SOL in rent + fees)` and dies
  with `dialoguer prompt failed: IO error: not a terminal` when run headless.
  Start it once from a real terminal; later launches reuse the PDA.
  (`pay server plans publish --spec … --write` writes the derived PDA back, but
  pay does not broadcast Plan accounts itself in v0.)
* **`mpp-session` did not complete with `pay curl` at 0.29.0 in sandbox.** The
  gateway issued a correct `intent="session"` challenge, but the client returned
  `Server returned 402 again after payment` on every attempt. Per-call
  (`mpp/charge`) and `subscription:` both worked. Prefer those for the hackathon.
* **Default bind is `0.0.0.0:1402`** for both `pay gate api` and the debugger —
  pass `--bind 127.0.0.1:PORT` if you don't want it on the LAN. The debugger UI
  shares the same port.
* **Non-TTY implies `--no-dna`**, which forces JSON output and non-interactive
  defaults. Errors arrive as `{"error":{"message":"…"}}` on stderr; the response
  body still lands on stdout, so pipelines work.
* **Free endpoints still proxy.** Leaving out `metering:`/`subscription:` means
  the gateway forwards without a 402 — a 404 from there is the upstream's 404.
* `pay --sandbox gate api` provisions and funds its own operator signer on
  Surfpool each boot; it does not touch the mainnet account.
* **High-intent commands to avoid running casually:** `pay send`,
  `pay account remove`, `pay account export` (writes the secret key to disk),
  `pay subscriptions cancel`. Hidden flag `--yolo-upto <microunits>` auto-pays
  challenges without prompting — do not put it in scripts.

### Environment variables worth knowing

| Variable | Purpose | Default |
|---|---|---|
| `PAY_API_URL` | pay-api host (balances, onramp) | `https://api.gateway-402.com` |
| `PAY_RPC_URL` | Solana RPC for the payment client | set by `--sandbox`/`--local` |
| `PAY_MAINNET_RPC_URL` | mainnet RPC for balance queries | `api.mainnet-beta.solana.com` |
| `PAY_ACTIVE_ACCOUNT` | force an account name | from `accounts.yml` |
| `PAY_CONFIG` | path to `pay.toml` | `./pay.toml`, then `~/.config/pay/pay.toml` |
| `NO_DNA` | mark caller as an agent: auto-pay + JSON output | unset |
| `RUST_LOG` | tracing filter (`--verbose` = `pay=info,warn`) | `warn` |

Precedence: explicit flags > env vars > `pay.toml` > built-in defaults.

---

## 7. Quick reference

```sh
pay --version
pay whoami                                   # address + balances
pay account list
pay --sandbox server demo                    # bundled demo gateway + debugger
pay server scaffold paywall.yml              # starter spec
pay --sandbox gate api paywall.yml --bind 127.0.0.1:1402
pay --sandbox curl http://127.0.0.1:1402/cheap
pay --sandbox --debugger curl <url>          # trace the payment exchange
pay skills                                   # browse the paid-API catalog
pay mcp                                      # MCP server for agent clients
```
