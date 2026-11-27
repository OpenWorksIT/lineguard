// LineGuard hotspot_events: Every hotspot's history: found, status changes, notes, and gone after reprocessing. Rows are only ever added.
// Generated from LineGuard's data format 1.0; see docs/data-format.md.
let
    Source = LineGuardTable("hotspot_events"),
    // en-US: the files always use a full stop for decimals, whatever this computer's region
    Typed = Table.TransformColumnTypes(Source, {
        {"site_id", type text},
        {"event_uid", type text},
        {"hotspot_uid", type text},
        {"event_number", Int64.Type},
        {"at_utc", type datetimezone},
        {"kind", type text},
        {"status", type text},
        {"note", type text},
        {"changed_by", type text}
    }, "en-US")
in
    Typed
