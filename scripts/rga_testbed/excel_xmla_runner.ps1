$ErrorActionPreference = "Stop"

function Convert-XmlaValue {
    param([object]$Value)
    if ($null -eq $Value -or $Value -is [System.DBNull]) {
        return $null
    }
    if ($Value -is [datetime]) {
        return $Value.ToString("o")
    }
    if (
        $Value -is [string] -or
        $Value -is [bool] -or
        $Value -is [byte] -or
        $Value -is [int16] -or
        $Value -is [int32] -or
        $Value -is [int64] -or
        $Value -is [single] -or
        $Value -is [double] -or
        $Value -is [decimal]
    ) {
        return $Value
    }
    return $Value.ToString()
}

try {
    Add-Type -AssemblyName "Microsoft.AnalysisServices.AdomdClient"
}
catch {
    throw (
        "Microsoft.AnalysisServices.AdomdClient is required for Excel XMLA capture. " +
        "Install the Microsoft ADOMD.NET client library on the runner host."
    )
}

$raw = [Console]::In.ReadToEnd()
if ([string]::IsNullOrWhiteSpace($raw)) {
    throw "Excel XMLA runner expected one JSON request on stdin."
}
$request = $raw | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace([string]$request.connection_string)) {
    throw "connection_string is required"
}
if ([string]::IsNullOrWhiteSpace([string]$request.query)) {
    throw "query is required"
}

$maxRows = [int]$request.max_rows
if ($maxRows -lt 1) {
    throw "max_rows must be positive"
}
$timeoutSeconds = [int]$request.timeout_seconds
if ($timeoutSeconds -lt 1) {
    throw "timeout_seconds must be positive"
}

$connection = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection([string]$request.connection_string)
try {
    $connection.Open()
    $command = $connection.CreateCommand()
    $command.CommandText = [string]$request.query
    $command.CommandTimeout = $timeoutSeconds
    $reader = $command.ExecuteReader()
    try {
        $columns = @()
        for ($i = 0; $i -lt $reader.FieldCount; $i++) {
            $columns += $reader.GetName($i)
        }

        $rows = @()
        while ($reader.Read()) {
            if ($rows.Count -ge $maxRows) {
                throw "XMLA result exceeded max_rows=$maxRows"
            }
            $row = @()
            for ($i = 0; $i -lt $reader.FieldCount; $i++) {
                $row += ,(Convert-XmlaValue $reader.GetValue($i))
            }
            $rows += ,$row
        }
    }
    finally {
        $reader.Close()
    }

    $result = [ordered]@{
        status = "PASS"
        columns = $columns
        rows = $rows
        metadata = [ordered]@{
            runner = "powershell_adomd"
            server_version = $connection.ServerVersion
            database = $connection.Database
        }
    }
    $result | ConvertTo-Json -Depth 10 -Compress
}
finally {
    if ($connection.State -ne [System.Data.ConnectionState]::Closed) {
        $connection.Close()
    }
    $connection.Dispose()
}
