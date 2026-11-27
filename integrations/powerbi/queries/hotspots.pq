// LineGuard hotspots: One row per confirmed hotspot, with its current status.
// Generated from LineGuard's data format 1.0; see docs/data-format.md.
let
    Source = LineGuardTable("hotspots"),
    // en-US: the files always use a full stop for decimals, whatever this computer's region
    Typed = Table.TransformColumnTypes(Source, {
        {"site_id", type text},
        {"hotspot_uid", type text},
        {"label", type text},
        {"flight_uid", type text},
        {"place_uid", type text},
        {"previous_hotspot_uid", type text},
        {"sighting_number", Int64.Type},
        {"is_latest_sighting", type logical},
        {"recurring", type logical},
        {"repairs_before", Int64.Type},
        {"latitude", type number},
        {"longitude", type number},
        {"temperature_rise_c", type number},
        {"previous_rise_c", type number},
        {"rise_change_c", type number},
        {"severity", type text},
        {"severity_rank", Int64.Type},
        {"status", type text},
        {"is_open", type logical},
        {"found_at_utc", type datetimezone},
        {"flown_at_utc", type datetimezone},
        {"status_changed_at_utc", type datetimezone},
        {"status_changed_by", type text},
        {"repaired_at_utc", type datetimezone},
        {"days_open", type number},
        {"note", type text},
        {"photos_confirming", Int64.Type},
        {"photos_covering", Int64.Type},
        {"photo_name", type text},
        {"tower_ref", type text},
        {"tower_kind", type text},
        {"tower_distance_m", type number},
        {"line_name", type text},
        {"line_voltage_kv", type number},
        {"line_operator", type text},
        {"google_maps_url", type text}
    }, "en-US")
in
    Typed
