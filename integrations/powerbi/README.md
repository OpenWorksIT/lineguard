# LineGuard in Power BI

Loads LineGuard's five tables into Power BI with the right column types, relationships and a starter set of measures. Format reference: [docs/data-format.md](../../docs/data-format.md).

## 1. Get the data

You have two options:

* **Live feed**, for a LineGuard server Power BI can reach over HTTPS. In the LineGuard dashboard, open **Data feed**, make a key for Power BI and copy it. The feed address is shown there too, for example `https://lineguard.example.com/api/data/v1/`.
* **Files**, for a site laptop without a connection. Run `lineguard export-data <folder>` (or use **Data feed → Download all data**) and put the files in a SharePoint or OneDrive folder.

## 2. Add the queries (Power BI Desktop)

1. **Home → Transform data** opens Power Query.
2. **Manage parameters → New parameter**. Name it `LineGuardFeed`, type Text, and set its value to the feed address. Keep the slash at the end.
3. **New source → Blank query → Advanced editor**. Paste [`queries/LineGuardTable.pq`](queries/LineGuardTable.pq) and name the query `LineGuardTable`. For files on SharePoint, swap the two `Source` lines in it as its comment explains.
4. Make one blank query per table, each named after its table: `sites`, `flights`, `hotspots`, `hotspot_events` and `revisits`. Paste the matching file from [`queries/`](queries/) into each one. These files set every column's type, using `en-US` number parsing, so decimals read correctly on any regional setting.
5. When Power BI asks for credentials on the feed address, choose **Basic**. The user name is `data` and the password is the data key. Power BI stores the key with its data source credentials, never in the report file.
6. Right-click `LineGuardTable` and untick **Enable load**. Then choose **Close & Apply**.

Scheduled refresh in the Power BI service needs the same credentials: under the semantic model's **Settings → Data source credentials**, choose Basic, user name `data`, and the key as the password. A server reachable from the internet over HTTPS needs no gateway. A LineGuard server inside a private network needs an on-premises data gateway that can reach it.

## 3. Relationships (Model view)

| From (many) | To (one) | Active |
|---|---|---|
| `flights[site_id]` | `sites[site_id]` | yes |
| `hotspots[flight_uid]` | `flights[flight_uid]` | yes |
| `hotspot_events[hotspot_uid]` | `hotspots[hotspot_uid]` | yes |
| `revisits[hotspot_uid]` | `hotspots[hotspot_uid]` | yes |
| `revisits[revisit_flight_uid]` | `flights[flight_uid]` | **no**: use `USERELATIONSHIP` when slicing revisits by the later flight |

Events whose `kind` is `gone` belong to hotspots that reprocessing no longer finds. They have no matching hotspot row, and Power BI groups them under a blank hotspot.

## 4. Measures

```DAX
Open faults =
CALCULATE ( COUNTROWS ( hotspots ), hotspots[is_open] = TRUE (), hotspots[is_latest_sighting] = TRUE () )

Open major faults =
CALCULATE ( [Open faults], hotspots[severity] = "major" )

Repaired =
CALCULATE ( COUNTROWS ( hotspots ), hotspots[status] = "repaired" )

Median days to repair =
CALCULATE ( MEDIAN ( hotspots[days_open] ), hotspots[status] = "repaired" )

Faults back after repair =
CALCULATE ( COUNTROWS ( hotspots ), hotspots[recurring] = TRUE () )

Repairs checked by a later flight =
CALCULATE ( COUNTROWS ( revisits ), revisits[status_at_revisit] = "repaired" )

Repairs that held =
CALCULATE ( COUNTROWS ( revisits ), revisits[outcome] = "repair_held" )

Repair hold rate =
DIVIDE ( [Repairs that held], [Repairs checked by a later flight] )

Average rise change at revisit (°C) =
AVERAGE ( revisits[rise_change_c] )
```

Count open faults with `is_latest_sighting`. A fault that several flights found has one row per flight, and this column keeps only the latest row for each spot.

## 5. Report ideas

* **Fault map:** a map visual with `hotspots[latitude]` and `hotspots[longitude]`, colour by `severity`, filtered to `is_open` and `is_latest_sighting`. Your organisation's Power BI admin may have to allow map visuals first.
* **One spot's history:** filter on `place_uid` and show `hotspots` by `flown_at_utc` next to `hotspot_events` by `at_utc`. Together they cover when the fault was found, repaired and checked again.
* **Repair quality:** `revisits[outcome]` by line or by tower, with `days_repair_to_revisit` for context.
* **Trend:** open faults by flight (`flights[flown_at_utc]`) and by severity.
