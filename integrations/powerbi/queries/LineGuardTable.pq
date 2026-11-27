// LineGuardTable: reads one LineGuard table. Make it once as a blank query named LineGuardTable.
// It reads the live feed by default. LineGuardFeed is a text parameter holding the feed address,
// e.g. https://lineguard.example.com/api/data/v1/  (Manage parameters → New parameter).
// Credentials: Basic, user name "data", password = a data key from the LineGuard dashboard.
// To read exported files from a SharePoint or OneDrive folder instead, use the second Source line.
(name as text) as table =>
let
    Source = Web.Contents(LineGuardFeed, [RelativePath = name & ".csv", Headers = [Accept = "text/csv"]]),
    // Source = SharePoint.Files("https://contoso.sharepoint.com/sites/assets", [ApiVersion = 15]){[Name = name & ".csv", #"Folder Path" = "https://contoso.sharepoint.com/sites/assets/Shared Documents/LineGuard/"]}[Content],
    Csv = Csv.Document(Source, [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Csv, [PromoteAllScalars = true]),
    // a blank cell means "not known": make it null before the columns are typed
    Blanks = Table.ReplaceValue(Promoted, "", null, Replacer.ReplaceValue, Table.ColumnNames(Promoted))
in
    Blanks
