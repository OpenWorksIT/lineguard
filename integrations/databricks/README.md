# LineGuard in Databricks

[`lineguard_load.py`](lineguard_load.py) is a Databricks notebook. It loads LineGuard's five tables into Unity Catalog as `lineguard_sites`, `lineguard_flights`, `lineguard_hotspots`, `lineguard_hotspot_events` and `lineguard_revisits`. Every table and column carries its description. The notebook also creates three views:

* `lineguard_open_faults`: open faults, one row per spot, worst first.
* `lineguard_repair_outcomes`: every repair a later flight checked, and whether it held.
* `lineguard_kpis`: headline numbers per site, including the repair hold rate and median days to repair.

Format reference: [docs/data-format.md](../../docs/data-format.md).

## Set up

1. **Workspace → Import → File**, and choose `lineguard_load.py`.
2. Create a Unity Catalog volume for the files, for example `main.lineguard.landing`.
3. Choose where the data comes from:
   * **Live feed.** In the LineGuard dashboard, open **Data feed** and make a key for Databricks. Store the key as a secret:
     `databricks secrets create-scope lineguard`, then `databricks secrets put-secret lineguard data-key`.
     Set the notebook's `source` to `feed` and `feeds` to the feed address. For several LineGuard servers, list their addresses separated by commas, with one secret name each in `secret_keys`. Outbound HTTPS from the compute must be allowed to the LineGuard address. On serverless, workspace egress rules can block it.
   * **Files from a site laptop.** Run `lineguard export-data` into a folder per site, for example `landing/<site name>/`. Get the folder into the volume by syncing, uploading or copying it. Set `source` to `volume`.
4. Set `catalog`, `schema` and `volume`, run the notebook once, then schedule it as a job (daily is plenty).

Each run replaces the tables, which suits LineGuard's small tables. Several sites stack into one table each. Every row carries its `site_id`, and every `_uid` is unique across sites.

## Example queries

```sql
-- faults that came back after a repair, newest first
SELECT site_id, label, line_name, tower_ref, repaired_at_utc, revisit_flown_at_utc, rise_at_revisit_c
FROM main.lineguard.lineguard_repair_outcomes
WHERE outcome = 'came_back_after_repair'
ORDER BY revisit_flown_at_utc DESC;

-- a single spot's whole history
SELECT h.label, h.flown_at_utc, h.temperature_rise_c, e.at_utc, e.kind, e.status, e.note, e.changed_by
FROM main.lineguard.lineguard_hotspots h
LEFT JOIN main.lineguard.lineguard_hotspot_events e USING (hotspot_uid)
WHERE h.place_uid = '<place_uid>'
ORDER BY coalesce(e.at_utc, h.flown_at_utc);
```
