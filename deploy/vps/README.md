# Hosting LineGuard behind an existing Caddy

LineGuard runs as its own Docker container behind a Caddy reverse proxy that already serves your other sites. This folder holds:
- `docker-compose.yml`: the LineGuard container;
- `lineguard.caddy`: the site block for Caddy;
- `.env.example`: settings.

**What it adds:**
- A `lineguard` container with its own data volume.
- One site file for Caddy.

**What it leaves alone:**
- It publishes no ports, so it doesn't clash with Caddy on 80 and 443.
- Other containers are untouched.
- CPU and memory are capped (1 CPU, 1.5 GB), so processing a flight can't starve other applications.
- The container is read-only, drops all Linux capabilities and can't gain new privileges.

LineGuard parses files uploaded by its users. Where you can, run it on a server or VM of its own, or at least give it a Docker network that only it and Caddy share.

## 1. DNS

Point an A (and/or AAAA) record for your chosen name, e.g. `lineguard.example.com`, at the server. Caddy gets the HTTPS certificate on its own once the record resolves.

## 2. Start LineGuard

```bash
git clone https://github.com/OpenWorksIT/lineguard ~/lineguard
cd ~/lineguard
git checkout v0.3.0                     # a release tag, not whatever is newest on main
cd deploy/vps
cp .env.example .env && chmod 600 .env
nano .env                               # LINEGUARD_PASSWORD (12+ characters), LINEGUARD_PUBLIC_URL, and a username of your own
docker network inspect edge >/dev/null 2>&1 || docker network create edge
docker compose up -d --build
docker compose ps                       # STATUS should become "healthy"
```

## 3. Connect it to Caddy

The Caddy container must be on the `edge` network:

```bash
docker network connect edge <your-caddy-container>      # once; or add the network to Caddy's compose file
```

Copy `lineguard.caddy` into the folder your Caddyfile imports, change `lineguard.example.com` to your name, then validate and reload. A reload has no downtime:

```bash
docker exec <your-caddy-container> caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile \
  && docker exec <your-caddy-container> caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

## 4. Try it with demo flights

```bash
docker compose exec lineguard lineguard demo                                  # 33 kV, cool morning
docker compose exec lineguard lineguard demo --scenario 33kv_hot --seed 2     # same line, hot afternoon
```

Each demo takes a minute or two to simulate, then a few seconds to process. Then open your LineGuard address and log in with the user and password from `.env`. Users can upload their own flights as a `.zip` of the folder from the drone's memory card.

## Update

```bash
cd ~/lineguard && git fetch --tags && git checkout v0.3.1    # the new release tag
cd deploy/vps && docker compose up -d --build
```

## Remove

Delete `lineguard.caddy` from Caddy's sites folder and reload Caddy, then:

```bash
cd ~/lineguard/deploy/vps && docker compose down        # add -v to delete LineGuard's data too
```

## Real DJI photos

Temperatures in DJI R-JPEGs are decoded with DJI's Thermal SDK. It isn't included in LineGuard: download it from DJI under DJI's own terms. Then:

1. Unpack it to `/opt/dji_thermal_sdk` on the server.
2. Uncomment the SDK volume in `docker-compose.yml`.
3. Set `LINEGUARD_DJI_IRP` in `.env`.
4. Run `docker compose up -d`.

The demo flights work without it.

## Upgrading from 0.2

0.3 needs two lines in `.env`:

- `LINEGUARD_PUBLIC_URL=https://<your LineGuard address>`, so phones pair over HTTPS.
- A `LINEGUARD_PASSWORD` of at least 12 characters. LineGuard refuses to start with a shorter one or the example one.

The Caddy site file has also changed (upload limits behind the login), so copy the new `lineguard.caddy` across too.
