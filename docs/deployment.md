# Deployment

> ## Status: NOT DEPLOYED
>
> **There is no public URL, and nothing in this document has been run against public
> infrastructure.** No VPS was provisioned, no domain registered, no certificate
> issued by a public CA, and nothing pushed to Vercel — this machine has no cloud
> credentials, no cloud CLI and no SSH key.
>
> What exists is the deployment *artefacts* — compose files, TLS material, edge
> config, limits, seeder — and **local verification of everything that does not
> require public infrastructure**, listed under "What has actually been verified"
> below. The remaining steps are written as instructions to run, not as a record of a
> deployment that happened.
>
> Do not read a passing line in this document as evidence about a deployed system.
> Where a verification could not be performed, it says so.

---

## The topology, and why it is split this way

| Host | Runs | Why there |
|---|---|---|
| **Main VPS** | core, core Postgres, connectors A and B with their own Postgres each, the edge model, Caddy | The demo needs to be cheap and self-contained |
| **Second VPS** | connector C and its Postgres, alone | So the distributed claim is true rather than modelled |
| **Vercel** | the dashboard | Static, read-only, and nowhere near the plaintext |

Connectors A and B share a kernel with core; their isolation is Docker's word, which
`tests/test_network_boundary.py` verifies. **C shares nothing** — different machine,
reaching core over the public internet with a client certificate. That is the
difference between a distributed architecture and a diagram of one.

C also proves the boundary is not an artefact of everything sitting on one host: it
submits over the internet, through mutual TLS, to a single endpoint, and can reach
nothing else.

---

## 1. Certificates

The federation CA signs core's server certificate and one client certificate per
remote institution. **The CA key never goes on either VPS** — it signs the identities
core trusts, so it belongs offline.

```bash
CORE_DOMAIN=core.example.org ./deploy/make-certs.sh deploy/certs psd_emcap03
```

Certificate subjects carry the **rotating pseudonym**, never the firm's name — the
same rule as `institution_ref` everywhere else. `tests/test_mtls.py` asserts it.

## 2. Main VPS

```bash
scp -r deploy services packages infra apps you@main-vps:/opt/marsad/
ssh you@main-vps
cd /opt/marsad/deploy

cat > .env <<'ENV'
CORE_DOMAIN=core.example.org
ACME_EMAIL=ops@example.org
CORE_DB_PASSWORD=<32+ random chars>
EDGE_DB_PASSWORD=<32+ random chars, different>
TOKEN_KEY=<32+ random chars>
EDGE_MODEL=qwen2.5:3b-instruct
LLM_DAILY_CALL_BUDGET=200
ENV
chmod 600 .env

docker compose -f docker-compose.main.yml up -d --build
docker compose -f docker-compose.main.yml exec ollama ollama pull qwen2.5:3b-instruct
```

The compose file uses `${VAR:?}` guards, so it **refuses to start** rather than
booting with a blank password. Verified locally: omitting `TOKEN_KEY` aborts with
`required variable TOKEN_KEY is missing a value`.

Point `core.example.org` at the main VPS before starting Caddy; ACME needs to resolve.

## 3. Second VPS

```bash
scp -r deploy/certs/{ca.crt,psd_emcap03.crt,psd_emcap03.key} you@vps-c:/opt/marsad/deploy/certs/
ssh you@vps-c
cd /opt/marsad/deploy

cat > .env <<'ENV'
CORE_DOMAIN=core.example.org
EDGE_DB_PASSWORD=<32+ random chars>
TOKEN_KEY=<the SAME key as the main VPS>
ENV
chmod 600 .env

docker compose -f docker-compose.remote.yml up -d --build
```

`TOKEN_KEY` is shared because tokens must be comparable across institutions or
correlation cannot fire. That is also precisely why the roadmap replaces HMAC with an
OPRF under threshold custody before real data — see `crypto/tokeniser.py`. **Do not
process real institutional data on this topology.**

## 4. Dashboard

```bash
cd apps/web
vercel --prod -e NEXT_PUBLIC_CORE_URL=https://core.example.org
```

`NEXT_PUBLIC_CONNECTORS` is left **empty** on purpose. Connectors hold plaintext; a
connector reachable from a public dashboard is a plaintext store on the internet. The
public demo is therefore read-only against core, and the intake panel works only when
the dashboard is served from the same host as a connector.

## 5. Seed the history

```bash
python3 deploy/seed_history.py \
  --almaha  https://core.example.org:8101 \
  --gulfsec https://core.example.org:8102 \
  --emcap   https://c.example.org:8103 \
  --core    https://core.example.org
```

Eight synthetic incidents across three institutions over three weeks, including two
cross-firm campaigns so the dashboard opens on a working correlation rather than an
empty table. Incidents enter **through a connector** — extraction, confirmation,
redaction — never written to core directly, so the history is one the architecture
could actually have produced.

All indicators are RFC 5737 / RFC 3849 documentation ranges and `.example` domains, so
no token can correspond to a real host.

---

## Limits, because this is public

| Limit | Where | Value |
|---|---|---|
| Public read requests | Caddy, per IP | 60/min |
| Submissions | Caddy, per client certificate | 30/min |
| Model calls | connector, `llm/budget.py` | `LLM_DAILY_CALL_BUDGET`, default 200/day |
| Public write surface | Caddy | none — `/v1/submissions` requires mutual TLS on :8443 |

An unmetered LLM endpoint on the open internet is someone else's free compute. When
the budget is spent, **extraction degrades to the deterministic extractor rather than
failing** — the connector must never be the reason an institution cannot file an
incident. On this project's own measurements the deterministic path is the more
accurate one anyway (`docs/model-path-results.md`), so the degraded mode is better on
most fields and merely lacks a model. The fallback is recorded on the draft, never
silent.

---

## What has actually been verified

Locally, on this machine. **None of it was run on public infrastructure.**

| Check | Command | Result |
|---|---|---|
| mTLS admits the right certificate, refuses none and refuses another CA's | `pytest tests/test_mtls.py` | **7 passed** |
| Connector refuses to downgrade when its certificate is missing | same | passed |
| Certificate subject carries a pseudonym, not a firm name | same | passed |
| Model budget degrades instead of failing | `pytest tests/test_extraction.py` | **35 passed** |
| Compose files parse, and refuse to start without secrets | `docker compose -f deploy/docker-compose.main.yml config` | valid; aborts without `TOKEN_KEY` |
| Seeder produces history and correlations | `python3 deploy/seed_history.py` | **8/8 submitted, 2 correlations** |
| Network boundary, inside real containers | `pytest tests/test_network_boundary.py -m docker` | **18 passed, 1 skipped** |
| Canary, incl. sweep of the live seeded core database | `pytest tests/test_canary.py` + direct SQL sweep | **passed; zero plaintext in 2430 chars of live rows** |
| Full suite | `pytest tests/` | **623 passed, 29 deselected** |

The canary sweep of the seeded database is the one worth repeating by hand:

```bash
docker compose exec -T core-db psql -U marsad -d marsad_core -tAc \
  "select string_agg(t::text,' ') from (select * from core.submissions) t" \
  | grep -iE "credential-harvesting|Finance staff|sso-verify|Al Maha|رصد" && echo LEAK || echo clean
```

It returns `clean`. What core holds looks like this — pseudonym, ATT&CK IDs, bands,
hour bucket, and nothing else:

```
(6cd0186a-…,1.0,psd_almaha01,["T1566.002","T1656"],BANK,LARGE,HIGH,"2026-08-12 09:00:00+00",,,,0,…)
```

## What has NOT been verified, and cannot be from here

- **The public URL, and TLS from a real CA.** Caddy's ACME flow needs a domain that
  resolves to the host. Untested.
- **Mutual TLS across a real network.** Verified against a loopback TLS server with
  the real certificates; not across the internet, and not through Caddy's
  `client_auth` block, whose config is unexercised.
- **The second VPS.** `docker-compose.remote.yml` parses and its connector image is
  the one already known to boot, but it has never run on separate hardware.
- **Vercel.** `vercel.json` is valid JSON with a CSP; never deployed.
- **The boundary tests against a deployed system.** They have been run against local
  containers only. Running them against two real hosts is the check that would
  actually retire the caveat in `docs/model-path-results.md` and the README about
  single-host simulation — see `test_the_single_host_limitation_is_recorded_rather_than_claimed_away`.
- **Rate limiting under load.** The Caddy `rate_limit` directive requires a plugin
  build (`caddy-ratelimit`); the stock `caddy:2.8-alpine` image does not include it,
  so the Caddyfile as written needs either a custom image or an alternative limiter.
  **This is a known gap in the artefact, not an oversight.**

## Cost

Roughly $18–30/month: main VPS 4GB (~$24 — the model needs the RAM), second VPS 1GB
(~$6), Vercel free tier, domain ~$12/year. The model is the only reason the main host
is not the cheapest tier available.
