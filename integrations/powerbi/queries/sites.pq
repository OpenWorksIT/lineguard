// LineGuard sites: The LineGuard server or laptop this export came from.
// Generated from LineGuard's data format 1.0; see docs/data-format.md.
let
    Source = LineGuardTable("sites"),
    // en-US: the files always use a full stop for decimals, whatever this computer's region
    Typed = Table.TransformColumnTypes(Source, {
        {"site_id", type text},
        {"site_name", type text},
        {"lineguard_version", type text},
        {"data_format_version", type text},
        {"exported_at_utc", type datetimezone},
        {"camera_timezone", type text}
    }, "en-US")
in
    Typed
