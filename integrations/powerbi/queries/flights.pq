// LineGuard flights: One row per processed drone flight.
// Generated from LineGuard's data format 1.0; see docs/data-format.md.
let
    Source = LineGuardTable("flights"),
    // en-US: the files always use a full stop for decimals, whatever this computer's region
    Typed = Table.TransformColumnTypes(Source, {
        {"site_id", type text},
        {"flight_uid", type text},
        {"flight_number", Int64.Type},
        {"flight_name", type text},
        {"flown_at_local", type datetime},
        {"flown_at_utc", type datetimezone},
        {"added_at_utc", type datetimezone},
        {"processing_status", type text},
        {"photos", Int64.Type},
        {"photos_skipped", Int64.Type},
        {"lines_found", Int64.Type},
        {"candidates_rejected", Int64.Type},
        {"standoff_m", type number},
        {"centre_latitude", type number},
        {"centre_longitude", type number},
        {"hotspots", Int64.Type},
        {"hotspots_open", Int64.Type},
        {"major_open", Int64.Type}
    }, "en-US")
in
    Typed
