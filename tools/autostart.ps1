<#
  A股人气雷达 - 开机自启管理

  用法（在项目根目录执行）：
    powershell -ExecutionPolicy Bypass -File tools\autostart.ps1 install
    powershell -ExecutionPolicy Bypass -File tools\autostart.ps1 uninstall
    powershell -ExecutionPolicy Bypass -File tools\autostart.ps1 status
    powershell -ExecutionPolicy Bypass -File tools\autostart.ps1 start
    powershell -ExecutionPolicy Bypass -File tools\autostart.ps1 stop

  说明：
    - 用一个"计划任务"实现，登录后 30 秒自动启动，并在每天 09:00 补启动一次
    - 已在运行则不会重复启动（MultipleInstances=IgnoreNew）
    - **默认完全隐藏启动**（走 run_hidden.vbs，不显示黑窗口）
      想改回"显示黑窗口"：加 -Visible
    - 卸载：uninstall；临时停止：stop
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('install', 'uninstall', 'status', 'start', 'stop')]
    [string]$Action = 'status',
    [string]$Exe = '',
    [switch]$Visible
)

$ErrorActionPreference = 'Stop'
$TaskName = 'A股人气雷达-自动启动'
$ProcName = 'A股人气雷达'

function ResolveExe {
    param([string]$p)
    if ($p -and $p.Trim()) {
        $full = [System.IO.Path]::GetFullPath($p)
        if (-not (Test-Path -LiteralPath $full)) { throw "找不到 exe: $full" }
        return $full
    }
    $root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    # 优先用 dist 下的 exe（当前在用的那份，数据也在 dist\data 里）；
    # 想固定到别的位置，用 -Exe "完整路径" 指定即可。
    $cands = @()
    # 1) 脚本自己所在目录（免安装包里 ps1 就和 exe 放一起）
    $cands += (Join-Path $PSScriptRoot 'A股人气雷达.exe')
    # 2) 项目里的 dist（当前正在用的那份，数据也在 dist\data）
    $cands += (Join-Path $root 'dist\A股人气雷达.exe')
    $rel = Get-ChildItem -LiteralPath $root -Directory -Filter 'A股人气雷达_v*' -ErrorAction SilentlyContinue |
           Sort-Object Name -Descending | Select-Object -First 1
    if ($rel) { $cands += (Join-Path $rel.FullName 'A股人气雷达.exe') }
    $cands += (Join-Path $root 'A股人气雷达.exe')
    foreach ($c in $cands) {
        $full = [System.IO.Path]::GetFullPath($c)
        if (Test-Path -LiteralPath $full) { return $full }
    }
    throw "找不到「A股人气雷达.exe」，请用 -Exe 指定完整路径"
}

switch ($Action) {

    'install' {
        $exePath = ResolveExe $Exe
        $workDir = Split-Path -Parent $exePath
        Write-Host "使用 exe : $exePath"

        $vbs = Join-Path $PSScriptRoot 'run_hidden.vbs'
        if ((-not $Visible) -and (Test-Path -LiteralPath $vbs)) {
            # 完全隐藏：由 wscript 以隐藏窗口方式拉起（不显示黑窗口）
            $taskAction = New-ScheduledTaskAction -Execute 'wscript.exe' `
                -Argument ('"' + $vbs + '" "' + $exePath + '"') -WorkingDirectory $workDir
            Write-Host "启动方式 : 完全隐藏（run_hidden.vbs）"
        } else {
            $taskAction = New-ScheduledTaskAction -Execute $exePath -Argument '--no-browser' -WorkingDirectory $workDir
            Write-Host "启动方式 : 显示黑窗口"
        }

        $t1 = New-ScheduledTaskTrigger -AtLogOn
        $t1.Delay = 'PT30S'
        $t2 = New-ScheduledTaskTrigger -Daily -At '09:00'

        $settings = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -MultipleInstances IgnoreNew `
            -RestartCount 3 `
            -RestartInterval (New-TimeSpan -Minutes 5) `
            -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
            -StartWhenAvailable

        $principal = New-ScheduledTaskPrincipal -UserId ("$env:USERDOMAIN\$env:USERNAME") `
            -LogonType Interactive -RunLevel Limited

        Register-ScheduledTask -TaskName $TaskName -Action $taskAction -Trigger @($t1, $t2) `
            -Settings $settings -Principal $principal -Force | Out-Null

        Write-Host ""
        Write-Host "已安装计划任务：$TaskName" -ForegroundColor Green
        Write-Host "  · 触发：登录后 30 秒 / 每天 09:00"
        Write-Host "  · 已在运行则跳过，不会开第二个"
        Write-Host "  · 后台静默运行，不显示黑窗口、不弹浏览器"
        Write-Host "  · 停止：powershell -File tools\autostart.ps1 stop"
        Write-Host "  · 卸载：powershell -File tools\autostart.ps1 uninstall"
    }

    'uninstall' {
        $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($t) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Write-Host "已卸载计划任务：$TaskName" -ForegroundColor Green
        } else {
            Write-Host "未安装该计划任务"
        }
    }

    'status' {
        $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        $running = @(Get-Process -Name $ProcName -ErrorAction SilentlyContinue).Count
        Write-Host "程序进程数     : $running"
        if ($t) {
            $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
            Write-Host "计划任务       : 已安装（状态 $($t.State)）" -ForegroundColor Green
            Write-Host "上次运行       : $($info.LastRunTime)  结果=$($info.LastTaskResult)"
            Write-Host "下次运行       : $($info.NextRunTime)"
        } else {
            Write-Host "计划任务       : 未安装" -ForegroundColor Yellow
        }
    }

    'start' {
        $running = @(Get-Process -Name $ProcName -ErrorAction SilentlyContinue).Count
        if ($running -gt 0) {
            Write-Host "程序已在运行（$running 个进程），跳过启动" -ForegroundColor Yellow
        } else {
            $exePath = ResolveExe $Exe
            $vbs = Join-Path $PSScriptRoot 'run_hidden.vbs'
            if ((-not $Visible) -and (Test-Path -LiteralPath $vbs)) {
                $null = & wscript.exe $vbs $exePath
            } else {
                Start-Process -FilePath $exePath -ArgumentList '--no-browser' `
                    -WorkingDirectory (Split-Path -Parent $exePath) -WindowStyle Hidden
            }
            Start-Sleep -Seconds 4
            Write-Host "已启动：$exePath" -ForegroundColor Green
        }
    }

    'stop' {
        $ps = @(Get-Process -Name $ProcName -ErrorAction SilentlyContinue)
        if ($ps.Count -eq 0) {
            Write-Host "程序未在运行"
        } else {
            $ps | Stop-Process -Force
            Write-Host "已停止 $($ps.Count) 个进程" -ForegroundColor Green
        }
    }
}
