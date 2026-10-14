#requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateSet('init','up','down','status','logs','restart-worker')]
    [string]$Action = 'up',
    [string]$ProjectRoot = (Join-Path $PSScriptRoot '../..')
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$runtime = Join-Path $ProjectRoot 'runtime/dev'
$secrets = Join-Path $runtime 'secrets'
$composeEnv = Join-Path $runtime 'compose.env'
$projectName = 'guichuhub-local'
$utf8 = [Text.UTF8Encoding]::new($false)
$passwordNames = @('superuser','api','worker','migration','backup') | ForEach-Object {"postgres_$($_)_password"}
$urlRoles = @('api','worker','migration')
$secretNames = @($passwordNames) + @($urlRoles | ForEach-Object {"$($_)_database_url"})

# Compose shell variables override --env-file values. Refuse inherited overrides
# so this entry point cannot accidentally reuse another environment's secrets/cache.
foreach($name in @('KICHU_DEV_SECRETS_DIR','KICHU_DEV_BACKEND_DEPS','KICHU_DEV_FRONTEND_DEPS')) {
    if([Environment]::GetEnvironmentVariable($name)) {
        throw "请先移除当前进程中的 $name 覆盖项，再使用独立开发入口。"
    }
}

foreach($required in @('compose.dev.yml','backend/uv.lock','frontend/package-lock.json')) {
    if(-not (Test-Path -LiteralPath (Join-Path $ProjectRoot $required) -PathType Leaf)) {
        throw "不是完整的 GuichuHub 项目目录，缺少 $required"
    }
}

function Assert-LocalPath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if(-not $full.StartsWith($ProjectRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw '开发运行目录必须位于当前项目内。'
    }
    $cursor = $full
    while($cursor -ne $ProjectRoot) {
        if(Test-Path -LiteralPath $cursor) {
            if((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw '开发运行目录包含链接，停止以保护其他数据。'
            }
        }
        $cursor = Split-Path -Parent $cursor
    }
}

function Initialize-Development {
    Assert-LocalPath $runtime
    Assert-LocalPath $secrets
    Assert-LocalPath $composeEnv
    foreach($name in $secretNames) { Assert-LocalPath (Join-Path $secrets $name) }
    $present = @($secretNames | Where-Object {Test-Path -LiteralPath (Join-Path $secrets $_)})
    if($present.Count -gt 0 -and $present.Count -ne $secretNames.Count) {
        throw '开发凭据不完整；停止以保留现有文件。请恢复与数据库匹配的完整凭据。'
    }
    $database = Join-Path $runtime 'postgres'
    Assert-LocalPath $database
    if($present.Count -eq 0 -and (Test-Path -LiteralPath $database) -and
       @(Get-ChildItem -LiteralPath $database -Force).Count -gt 0) {
        throw '已有开发数据库但缺少凭据；停止生成新密码，避免失去数据库访问。'
    }
    if($present.Count -eq 0) {
        $values = @{}
        foreach($name in $passwordNames) {
            $values[$name] = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).ToLowerInvariant()
        }
        foreach($role in $urlRoles) {
            $password = $values["postgres_$($role)_password"]
            $values["$($role)_database_url"] = "postgresql+psycopg://kichu_$($role):$password@postgres:5432/kichu"
        }
        New-Item -ItemType Directory -Path $secrets -Force | Out-Null
        foreach($name in $secretNames) {
            $stream = [IO.File]::Open((Join-Path $secrets $name), [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            try {
                $bytes = $utf8.GetBytes($values[$name])
                $stream.Write($bytes,0,$bytes.Length)
            } finally { $stream.Dispose() }
        }
    } else {
        $values = @{}
        foreach($name in $secretNames) {
            $values[$name] = [IO.File]::ReadAllText((Join-Path $secrets $name)).Trim()
        }
        foreach($name in $passwordNames) {
            if($values[$name] -notmatch '^[a-f0-9]{64}$') { throw '开发凭据格式不符；未修改现有文件。' }
        }
        foreach($role in $urlRoles) {
            $password = $values["postgres_$($role)_password"]
            if($values["$($role)_database_url"] -cne "postgresql+psycopg://kichu_$($role):$password@postgres:5432/kichu") {
                throw '开发数据库 URL 与本地角色密码不匹配；未修改现有文件。'
            }
        }
    }
    foreach($directory in @('private','logs')) {
        $path = Join-Path $runtime $directory
        Assert-LocalPath $path
        New-Item -ItemType Directory -Path $path -Force | Out-Null
    }
    $backendKey = (Get-FileHash -LiteralPath (Join-Path $ProjectRoot 'backend/uv.lock') -Algorithm SHA256).Hash.ToLowerInvariant().Substring(0,12)
    $frontendKey = (Get-FileHash -LiteralPath (Join-Path $ProjectRoot 'frontend/package-lock.json') -Algorithm SHA256).Hash.ToLowerInvariant().Substring(0,12)
    # Non-secret, generated settings. New lockfiles use new dependency volumes;
    # existing dependency caches and PostgreSQL data are never deleted.
    $settings = "KICHU_DEV_BACKEND_DEPS=$backendKey`nKICHU_DEV_FRONTEND_DEPS=$frontendKey`n"
    [IO.File]::WriteAllText($composeEnv,$settings,$utf8)
    Write-Host "本地开发配置已就绪：$runtime（凭据不会输出或覆盖）"
}

function Invoke-Docker([string[]]$Arguments) {
    & docker @Arguments
    if($LASTEXITCODE -ne 0) { throw 'Docker 命令失败；已保留开发数据，请检查上方错误。' }
}

if($Action -in @('init','up')) { Initialize-Development }
if($Action -eq 'init') { return }
$endpoint = (& docker context inspect --format '{{.Endpoints.docker.Host}}' 2>$null | Out-String).Trim()
if($LASTEXITCODE -ne 0 -or $endpoint -notmatch '^(npipe|unix)://') {
    throw '请使用本机 Docker Desktop / Unix socket 上下文，不能在远程 Docker 主机初始化本地开发环境。'
}
& docker info --format '{{.ServerVersion}}' | Out-Null
if($LASTEXITCODE -ne 0) { throw 'Docker 引擎未就绪；请先启动 Docker Desktop，保留现有数据，不要恢复出厂设置。' }
$compose = @('compose','--project-directory',$ProjectRoot,'-p',$projectName,'-f',(Join-Path $ProjectRoot 'compose.dev.yml'))
if(Test-Path -LiteralPath $composeEnv) { $compose += @('--env-file',$composeEnv) }

switch($Action) {
    'up' {
        Invoke-Docker ($compose + @('build'))
        Invoke-Docker ($compose + @('up','-d','--wait','postgres'))
        Invoke-Docker ($compose + @('--profile','maintenance','run','--rm','--build','migrate'))
        Invoke-Docker ($compose + @('up','-d'))
        $ready = $false
        for($attempt=0; $attempt -lt 60; $attempt++) {
            try {
                $response = Invoke-WebRequest -Uri 'http://127.0.0.1:5000/api/health/ready' -TimeoutSec 3 -NoProxy
                if($response.StatusCode -eq 200) { $ready=$true; break }
            } catch { }
            Start-Sleep -Seconds 2
        }
        if(-not $ready) { throw 'API readiness 未通过；数据已保留，请运行 dev.ps1 logs 查看原因。' }
        Write-Host '开发环境已启动：http://127.0.0.1:5174；API readiness 已通过。'
        Invoke-Docker ($compose + @('ps'))
    }
    'down' { Invoke-Docker ($compose + @('down')) }
    'status' { Invoke-Docker ($compose + @('ps')) }
    'logs' { Invoke-Docker ($compose + @('logs','--tail','100')) }
    'restart-worker' { Invoke-Docker ($compose + @('restart','worker')) }
}
