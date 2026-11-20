# ASCII source for Windows PowerShell 5.1; stdin/stdout are UTF-8 JSON lines.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

function Get-ClaudeSnapshot($Request) {
    $handle = [long]0
    if ($null -ne $Request.hwnd) {
        $handle = [long]$Request.hwnd
    } else {
        $candidate = Get-Process -Name claude -ErrorAction SilentlyContinue |
            Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero } |
            Sort-Object @{ Expression = { $_.MainWindowTitle -ne 'Claude' } }, Id |
            Select-Object -First 1
        if ($null -ne $candidate) { $handle = $candidate.MainWindowHandle.ToInt64() }
    }
    if ($handle -le 0) { throw 'Claude window not found' }
    $root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$handle)
    $owner = [System.Diagnostics.Process]::GetProcessById($root.Current.ProcessId)
    if ($owner.ProcessName -ine 'claude') { throw 'Window is not Claude' }
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Button)
    $buttons = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
    $names = @()
    foreach ($button in $buttons) { $names += [string]$button.Current.Name }
    $current = ''
    $renameSuffix = ', rename session'
    $morePrefix = 'More options for '
    $entries = @()
    for ($i = 0; $i -lt $buttons.Count; $i++) {
        $name = $names[$i]
        if ($name.EndsWith($renameSuffix, [StringComparison]::Ordinal)) {
            $current = $name.Substring(0, $name.Length - $renameSuffix.Length)
        }
        $j = $i + 1
        # A session with child sessions has a "Hide/Show nested sessions <title>" button in between.
        if ($j -lt $buttons.Count -and ($names[$j].StartsWith('Hide nested sessions ', [StringComparison]::Ordinal) -or
                $names[$j].StartsWith('Show nested sessions ', [StringComparison]::Ordinal))) { $j++ }
        if ($j -ge $buttons.Count) { continue }
        $next = $names[$j]
        if (-not $next.StartsWith($morePrefix, [StringComparison]::Ordinal)) { continue }
        $title = $next.Substring($morePrefix.Length)
        if (-not $title) { continue }
        if ($name -ceq $title) {
            $status = ''
        } elseif ($name.StartsWith($title + ' ', [StringComparison]::Ordinal)) {
            $status = $name.Substring($title.Length).Trim()
        } else { continue }
        $entries += @{ title = $title; status = $status; button = $buttons[$i] }
    }
    return @{ hwnd = $handle; current_title = $current; entries = @($entries) }
}

while ($null -ne ($line = [Console]::ReadLine())) {
    $request = $null
    try {
        $request = $line | ConvertFrom-Json
        if ($request.command -cne 'list' -and $request.command -cne 'invoke') {
            throw 'Unknown command'
        }
        $snapshot = Get-ClaudeSnapshot $request
        if ($request.command -ceq 'list') {
            $sessions = @($snapshot.entries | ForEach-Object {
                @{ title = $_.title; status = $_.status }
            })
            $response = @{ ok = $true; id = $request.id; hwnd = $snapshot.hwnd;
                           current_title = $snapshot.current_title; sessions = @($sessions) }
        } else {
            $matching = @($snapshot.entries | Where-Object { $_.title -ceq $request.title })
            $index = [int]$request.index
            if ($index -lt 0 -or $index -ge $matching.Count) { throw 'Session title not found' }
            [object]$pattern = $null
            $target = $matching[$index].button
            if (-not $target.TryGetCurrentPattern(
                    [System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) {
                throw 'Session button does not support InvokePattern'
            }
            ([System.Windows.Automation.InvokePattern]$pattern).Invoke()
            $response = @{ ok = $true; id = $request.id; hwnd = $snapshot.hwnd;
                           title = $request.title; index = $index; matches = $matching.Count }
        }
    } catch {
        $response = @{ ok = $false; id = $request.id; error = $_.Exception.Message }
    }
    [Console]::Out.WriteLine(($response | ConvertTo-Json -Compress -Depth 5))
    [Console]::Out.Flush()
}
