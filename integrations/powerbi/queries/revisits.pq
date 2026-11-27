// LineGuard revisits: Each later flight that passed over a hotspot's spot, and what it found there.
// Generated from LineGuard's data format 1.0; see docs/data-format.md.
let
    Source = LineGuardTable("revisits"),
    // en-US: the files always use a full stop for decimals, whatever this computer's region
    Typed = Table.TransformColumnTypes(Source, {
        {"site_id", type text},
        {"revisit_uid", type text},
        {"hotspot_uid", type text},
        {"place_uid", type text},
        {"revisit_flight_uid", type text},
        {"hotspot_flown_at_utc", type datetimezone},
        {"revisit_flown_at_utc", type datetimezone},
        {"days_between", type number},
        {"status_at_revisit", type text},
        {"repaired_at_utc", type datetimezone},
        {"days_repair_to_revisit", type number},
        {"found_again", type logical},
        {"later_hotspot_uid", type text},
        {"rise_before_c", type number},
        {"rise_at_revisit_c", type number},
        {"rise_change_c", type number},
        {"outcome", type text},
        {"nearest_photo_m", type number}
    }, "en-US")
in
    Typed
