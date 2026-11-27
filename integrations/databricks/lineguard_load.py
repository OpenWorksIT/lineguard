# Databricks notebook source
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenWorks IT (Pty) Ltd
#
# LineGuard → Databricks
# Loads LineGuard's open data (flights, hotspots, their history and revisits) into Unity Catalog
# tables, with every table and column described. Import this file into a workspace
# (Workspace → Import → File) and run it as a scheduled job.
#
# Where the data comes from, one of:
#   feed    LineGuard's live feed: one or more servers, each read with its own data key.
#   volume  Files written by "lineguard export-data" into a Unity Catalog volume, one folder per
#           site (for site laptops with no connection to Databricks: sync the folder, or upload it).
#
# Each run replaces the tables, which is right for LineGuard's small tables. Exports from several
# sites are stacked: every row carries its site_id, and every ID ending in _uid is unique everywhere.
# Format reference: https://github.com/OpenWorksIT/lineguard/blob/main/docs/data-format.md

# COMMAND ----------

dbutils.widgets.dropdown("source", "feed", ["feed", "volume"], "Data source")
dbutils.widgets.text("feeds", "https://lineguard.example.com/api/data/v1/", "Feed addresses (comma separated)")
dbutils.widgets.text("secret_scope", "lineguard", "Secret scope holding the data keys")
dbutils.widgets.text("secret_keys", "data-key", "Secret names, one per feed (comma separated)")
dbutils.widgets.text("volume", "/Volumes/main/lineguard/landing", "Volume folder (one subfolder per site)")
dbutils.widgets.text("catalog", "main", "Catalog")
dbutils.widgets.text("schema", "lineguard", "Schema")

SOURCE = dbutils.widgets.get("source")
FEEDS = [u.strip() for u in dbutils.widgets.get("feeds").split(",") if u.strip()]
SCOPE = dbutils.widgets.get("secret_scope")
SECRETS = [k.strip() for k in dbutils.widgets.get("secret_keys").split(",") if k.strip()]
VOLUME = dbutils.widgets.get("volume").rstrip("/")
TARGET = f"`{dbutils.widgets.get('catalog')}`.`{dbutils.widgets.get('schema')}`"
TABLES = ["sites", "flights", "hotspots", "hotspot_events", "revisits"]

# COMMAND ----------

# Fetch from the live feed(s) into the volume, so every run reads the same way and the last
# copy of each site's files stays in the volume. Feed mode needs outbound HTTPS from the cluster
# (serverless egress rules may need the LineGuard address allowed).
import json
import os
import urllib.request


def fetch(url, key):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "User-Agent": "lineguard-databricks"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


if SOURCE == "feed":
    if len(SECRETS) != len(FEEDS):
        raise ValueError("Give one secret name per feed address.")
    for feed, secret in zip(FEEDS, SECRETS):
        base = feed.rstrip("/") + "/"
        key = dbutils.secrets.get(SCOPE, secret)
        sites = fetch(base + "sites.csv", key).decode("utf-8").splitlines()
        site_id = sites[1].split(",")[0]                       # one site per feed
        folder = f"{VOLUME}/{site_id}"
        os.makedirs(folder, exist_ok=True)
        for name in TABLES:
            data = fetch(base + f"{name}.parquet", key)
            if data[:4] != b"PAR1":
                raise ValueError(f"{base}{name}.parquet is not a Parquet file")
            tmp = f"{folder}/.{name}.parquet.tmp"
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, f"{folder}/{name}.parquet")
        with open(f"{folder}/datapackage.json", "wb") as fh:
            fh.write(fetch(base + "datapackage.json", key))
        print(f"{feed}: site {site_id} fetched")

# COMMAND ----------

# Load every site's files into one table each, then describe the tables and columns from
# datapackage.json so they read well in Catalog Explorer and Genie.
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {TARGET}")

descriptions = {}
for entry in sorted(os.listdir(VOLUME)):
    dp = f"{VOLUME}/{entry}/datapackage.json"
    if os.path.isfile(dp):
        with open(dp) as fh:
            for res in json.load(fh)["resources"]:
                descriptions.setdefault(res["name"].removesuffix("_parquet"), res)

for name in TABLES:
    files = f"{VOLUME}/*/{name}.parquet"
    df = spark.read.parquet(files)
    table = f"{TARGET}.`lineguard_{name}`"
    (df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table))
    res = descriptions.get(name)
    if res:
        def q(text):
            return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"
        spark.sql(f"COMMENT ON TABLE {table} IS {q('LineGuard: ' + res['title'])}")
        for field in res["schema"]["fields"]:
            spark.sql(f"ALTER TABLE {table} ALTER COLUMN `{field['name']}` COMMENT {q(field['description'])}")
    print(f"{table}: {spark.table(table).count()} rows")

# COMMAND ----------

# Ready-made views for the questions asked most.
spark.sql(f"""
CREATE OR REPLACE VIEW {TARGET}.lineguard_open_faults
COMMENT 'Open LineGuard faults, one row per spot (the latest sighting), worst first'
AS SELECT h.*, f.flight_name, s.site_name
FROM {TARGET}.lineguard_hotspots h
JOIN {TARGET}.lineguard_flights f USING (flight_uid)
JOIN {TARGET}.lineguard_sites s ON s.site_id = h.site_id
WHERE h.is_open AND h.is_latest_sighting
ORDER BY h.severity_rank DESC, h.temperature_rise_c DESC
""")

spark.sql(f"""
CREATE OR REPLACE VIEW {TARGET}.lineguard_repair_outcomes
COMMENT 'Each repair checked by a later flight: did it hold or did the fault come back'
AS SELECT r.site_id, r.hotspot_uid, r.place_uid, h.label, h.line_name, h.tower_ref,
       r.repaired_at_utc, r.revisit_flown_at_utc, r.days_repair_to_revisit,
       r.outcome, r.rise_before_c, r.rise_at_revisit_c
FROM {TARGET}.lineguard_revisits r
JOIN {TARGET}.lineguard_hotspots h USING (hotspot_uid)
WHERE r.status_at_revisit = 'repaired'
""")

spark.sql(f"""
CREATE OR REPLACE VIEW {TARGET}.lineguard_kpis
COMMENT 'LineGuard headline numbers per site'
AS WITH faults AS (
  SELECT site_id,
         count_if(is_open AND is_latest_sighting) AS open_faults,
         count_if(is_open AND is_latest_sighting AND severity = 'major') AS open_major,
         count_if(status = 'repaired') AS repaired,
         percentile_approx(CASE WHEN status = 'repaired' THEN days_open END, 0.5) AS median_days_to_repair,
         count_if(recurring) AS came_back_after_repair
  FROM {TARGET}.lineguard_hotspots GROUP BY site_id
), checks AS (
  SELECT site_id, count(*) AS repairs_checked, count_if(outcome = 'repair_held') AS repairs_held
  FROM {TARGET}.lineguard_revisits WHERE status_at_revisit = 'repaired' GROUP BY site_id
)
SELECT s.site_id, s.site_name, s.exported_at_utc,
       coalesce(f.open_faults, 0) AS open_faults, coalesce(f.open_major, 0) AS open_major,
       coalesce(f.repaired, 0) AS repaired, f.median_days_to_repair,
       coalesce(f.came_back_after_repair, 0) AS came_back_after_repair,
       coalesce(c.repairs_checked, 0) AS repairs_checked,
       c.repairs_held / nullif(c.repairs_checked, 0) AS repair_hold_rate
FROM {TARGET}.lineguard_sites s
LEFT JOIN faults f USING (site_id)
LEFT JOIN checks c USING (site_id)
""")
display(spark.table(f"{TARGET}.lineguard_kpis"))
