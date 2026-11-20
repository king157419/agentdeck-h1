# ASCII source for Windows PowerShell 5.1; stdin/stdout are UTF-8 JSON lines.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class AgentDeckForeground {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
}
'@

function Get-WindowRoot($Request) {
    $handle = [long]$Request.hwnd
    if ($handle -le 0) { throw 'Window handle required' }
    return [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$handle)
}

function Get-Prompt($Root) {
    $condition = New-Object System.Windows.Automation.AndCondition(
        (New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::Edit)),
        (New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::NameProperty, 'Prompt')))
    $prompt = $Root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)
    if ($null -eq $prompt) { throw 'Prompt input not found' }
    return $prompt
}

function Get-ScrollPanes($Root) {
    $window = $Root.Current.BoundingRectangle
    $minimum = $window.Width * $window.Height * 0.04
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::IsScrollPatternAvailableProperty, $true)
    $elements = $Root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
    $panes = @()
    foreach ($element in $elements) {
        [object]$pattern = $null
        if (-not $element.TryGetCurrentPattern([System.Windows.Automation.ScrollPattern]::Pattern, [ref]$pattern)) { continue }
        if (-not ([System.Windows.Automation.ScrollPattern]$pattern).Current.VerticallyScrollable) { continue }
        $rect = $element.Current.BoundingRectangle
        if ($rect.IsEmpty -or $rect.Width * $rect.Height -lt $minimum) { continue }
        $panes += @{ rect = @($rect.Left, $rect.Top, $rect.Right, $rect.Bottom);
                     area = $rect.Width * $rect.Height }
    }
    $panes = @($panes | Sort-Object -Property @{Expression={$_.area};Descending=$true} |
        Select-Object -First 4 | Sort-Object -Property @{Expression={$_.rect[0]}})
    if ($panes.Count -eq 0) {
        $panes = @(@{ rect = @($window.Left, $window.Top, $window.Right, $window.Bottom) })
    }
    return $panes
}

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
    return @{ hwnd = $handle; current_title = $current; entries = @($entries); names = @($names) }
}

while ($null -ne ($line = [Console]::ReadLine())) {
    $request = $null
    try {
        $request = $line | ConvertFrom-Json
        if ($request.command -notin @('list', 'invoke', 'panes', 'prompt_text', 'focus_prompt', 'click', 'focused_editable')) {
            throw 'Unknown command'
        }
        if ($request.command -in @('list', 'invoke')) { $snapshot = Get-ClaudeSnapshot $request }
        else { $root = Get-WindowRoot $request }
        if ($request.command -in @('focus_prompt', 'click') -and
                [AgentDeckForeground]::GetForegroundWindow().ToInt64() -ne [long]$request.hwnd) {
            throw 'Target is no longer foreground'
        }
        if ($request.command -ceq 'panes') {
            $response = @{ok=$true; id=$request.id; hwnd=$request.hwnd; panes=@(Get-ScrollPanes $root)}
        } elseif ($request.command -ceq 'prompt_text') {
            $prompt = Get-Prompt $root
            [object]$value = $null
            if (-not $prompt.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$value)) {
                throw 'Prompt does not support ValuePattern'
            }
            $response = @{ok=$true; id=$request.id; text=([System.Windows.Automation.ValuePattern]$value).Current.Value}
        } elseif ($request.command -ceq 'focus_prompt') {
            (Get-Prompt $root).SetFocus()
            $response = @{ok=$true; id=$request.id}
        } elseif ($request.command -ceq 'focused_editable') {
            $focused = [System.Windows.Automation.AutomationElement]::FocusedElement
            $editable = $false
            $belongs = $false
            $ancestor = $focused
            while ($null -ne $ancestor) {
                if ([System.Windows.Automation.Automation]::Compare($ancestor, $root)) { $belongs = $true; break }
                $ancestor = [System.Windows.Automation.TreeWalker]::RawViewWalker.GetParent($ancestor)
            }
            if ($null -ne $focused -and $belongs) {
                [object]$value = $null
                $editable = $focused.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit
                if ($focused.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$value)) {
                    $editable = $editable -or -not ([System.Windows.Automation.ValuePattern]$value).Current.IsReadOnly
                }
                $editable = $editable -and $focused.Current.IsEnabled
            }
            $response = @{ok=$true; id=$request.id; editable=$editable}
        } elseif ($request.command -ceq 'click') {
            $condition = New-Object System.Windows.Automation.AndCondition(
                (New-Object System.Windows.Automation.PropertyCondition(
                    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
                    [System.Windows.Automation.ControlType]::Button)),
                (New-Object System.Windows.Automation.PropertyCondition(
                    [System.Windows.Automation.AutomationElement]::NameProperty, [string]$request.name)))
            $button = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)
            if ($null -eq $button) { throw 'Button not found' }
            [object]$pattern = $null
            if (-not $button.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) {
                throw 'Button does not support InvokePattern'
            }
            ([System.Windows.Automation.InvokePattern]$pattern).Invoke()
            $response = @{ok=$true; id=$request.id}
        } elseif ($request.command -ceq 'list') {
            $sessions = @($snapshot.entries | ForEach-Object {
                @{ title = $_.title; status = $_.status }
            })
            $response = @{ ok = $true; id = $request.id; hwnd = $snapshot.hwnd;
                           current_title = $snapshot.current_title; sessions = @($sessions);
                           buttons = @($snapshot.names) }
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
