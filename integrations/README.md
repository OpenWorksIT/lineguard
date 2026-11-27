# Integrations

LineGuard exports flights, hotspots, each hotspot's history and every revisit in a documented open format: [docs/data-format.md](../docs/data-format.md). The tables are Parquet and CSV, described by a [Frictionless Data Package](https://datapackage.org) descriptor.

* [Power BI](powerbi/): typed Power Query queries, relationships and measures.
* [Databricks](databricks/): a notebook that loads one or more sites into Unity Catalog, with ready-made views.
* Anything else (Excel, DuckDB, PostgreSQL, Python, R): read the Parquet or CSV files directly.

Ways to get the data out of LineGuard:

| | How | Suits |
|---|---|---|
| Live feed | `https://<server>/api/data/v1/<table>.parquet` or `.csv`, with a read-only data key (dashboard → Data feed) | A hosted server, or a laptop the reporting tool can reach |
| Folder | `lineguard export-data <folder>` (run it from a timer to keep the folder fresh) | Site laptops: write into a OneDrive, SharePoint or Databricks folder that syncs when there is signal |
| Download | Dashboard → Data feed → Download all data | Once-off reports |

`python integrations/generate.py` regenerates the format guide and the Power Query files from `lineguard/opendata.py`. The tests fail if they are out of date.
