<#
gpu-maid tray — Windows system-tray companion, zero dependencies.

Sits in the notification area and shows the maid's state as a colored dot:
  green = free VRAM > 2G   orange = > 0.5G   red = less
  purple = master switch off   gray = agent unreachable
Right-click: residents (click to wake/sleep), master switch, exit.

Usage:
  powershell -NoProfile -ExecutionPolicy Bypass -File gpu-maid-tray.ps1 `
      [-Url http://127.0.0.1:9700] [-IntervalSec 5]

  -SelfTest : print one status snapshot and exit (no tray) — handy over SSH.

Autostart and options: see tray/README.md.
#>

param(
    [string]$Url = "http://127.0.0.1:9700",
    [int]$IntervalSec = 5,
    [switch]$SelfTest
)

function Get-Maid {
    try { return Invoke-RestMethod -Uri "$Url/list" -TimeoutSec 3 }
    catch { return $null }
}

function Invoke-Maid([string]$Path) {
    # fire-and-forget: the agent blocks through make-room, so never run
    # POSTs on the tray's UI thread.
    $ps = [powershell]::Create().AddScript(
        "try { Invoke-RestMethod -Uri '$Url/$Path' -Method Post -TimeoutSec 60 | Out-Null } catch { }")
    [void]$ps.BeginInvoke()
}

function Format-Status($d) {
    if ($null -eq $d) { return "maid unreachable" }
    if ($d.master_off) { return "master off — GPU is the owner's" }
    $g = $d.gpu
    if ($null -eq $g.free_gb) { return "GPU telemetry unavailable" }
    $t = "GPU {0}/{1}G" -f $g.free_gb, $g.total_gb
    if ($null -ne $g.util_pct) { $t += " - {0}%" -f $g.util_pct }
    if ($null -ne $g.temp_c)  { $t += " - {0}C" -f $g.temp_c }
    return $t
}

if ($SelfTest) {
    $d = Get-Maid
    Write-Output (Format-Status $d)
    if ($d) {
        foreach ($p in $d.residents.PSObject.Properties) {
            $r = $p.Value
            $state = if ($r.alive) { "up" } elseif ($r.suspended) { "suspended" } else { "down" }
            Write-Output ("  {0}: {1}  {2}G  {3}" -f $p.Name, $state, $r.vram_gb, $r.protocol)
        }
    }
    exit 0
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function New-DotIcon([string]$hex) {
    $bmp = New-Object System.Drawing.Bitmap(16, 16)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = 'AntiAlias'
    $g.Clear([System.Drawing.Color]::Transparent)
    $brush = New-Object System.Drawing.SolidBrush(
        [System.Drawing.ColorTranslator]::FromHtml($hex))
    $g.FillEllipse($brush, 1, 1, 13, 13)
    $brush.Dispose(); $g.Dispose()
    $ico = [System.Drawing.Icon]::FromHandle($bmp.GetHicon())
    $bmp.Dispose()
    return $ico
}

$Icons = @{
    green  = New-DotIcon '#2e9e4f'
    orange = New-DotIcon '#d29922'
    red    = New-DotIcon '#c93636'
    purple = New-DotIcon '#8250df'
    gray   = New-DotIcon '#8b949e'
}

$tray = New-Object System.Windows.Forms.NotifyIcon
$tray.Visible = $true
$tray.Text = 'gpu-maid'

function Invoke-MaidAsync($path) { Invoke-Maid $path; Refresh-Now }

function Build-Menu($d) {
    $menu = New-Object System.Windows.Forms.ContextMenuStrip
    [void]$menu.Items.Add((Format-Status $d))
    [void]$menu.Items.Add('-')
    if ($null -ne $d) {
        foreach ($p in $d.residents.PSObject.Properties) {
            $r = $p.Value; $n = $p.Name
            if ($r.alive) { $label = "[up]   $n"; $action = "sleep/$n" }
            elseif ($r.suspended) { $label = "[zzz]  $n"; $action = "wake/$n" }
            else { $label = "[down] $n"; $action = "wake/$n" }
            $item = $menu.Items.Add($label)
            $item.Tag = $action
            $item.add_Click({ param($s, $e) Invoke-Maid $s.Tag; Refresh-Now })
        }
        [void]$menu.Items.Add('-')
        if ($d.master_off) {
            $mi = $menu.Items.Add('master ON')
            $mi.add_Click({ Invoke-Maid 'master/on'; Refresh-Now })
        } else {
            $mi = $menu.Items.Add('master OFF (give the GPU back)')
            $mi.add_Click({ Invoke-Maid 'master/off'; Refresh-Now })
        }
    } else {
        $retry = $menu.Items.Add("agent unreachable at $Url")
        $retry.add_Click({ Refresh-Now })
    }
    [void]$menu.Items.Add('-')
    $exit = $menu.Items.Add('exit')
    $exit.add_Click({
        $script:tray.Visible = $false
        $script:timer.Stop()
        [System.Windows.Forms.Application]::ExitThread()
    })
    return $menu
}

function Refresh-Now {
    $d = Get-Maid
    $tray.Text = (Format-Status $d)
    $hex = 'gray'
    if ($null -ne $d) {
        if ($d.master_off) { $hex = 'purple' }
        elseif ($null -ne $d.gpu.free_gb) {
            $f = [double]$d.gpu.free_gb
            if ($f -gt 2) { $hex = 'green' } elseif ($f -gt 0.5) { $hex = 'orange' }
            else { $hex = 'red' }
        }
    }
    $tray.Icon = $Icons[$hex]
    $old = $tray.ContextMenuStrip
    $tray.ContextMenuStrip = Build-Menu $d
    if ($old) { $old.Dispose() }
}

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = $IntervalSec * 1000
$timer.add_Tick({ Refresh-Now })

Refresh-Now
$timer.Start()
[System.Windows.Forms.Application]::Run()
