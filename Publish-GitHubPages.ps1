#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,37}[a-zA-Z0-9])?$')][string]$Owner,
    [ValidatePattern('^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$')][string]$Repository = 'conus-monthly-atlas',
    [switch]$UseExistingEmpty
)
$ErrorActionPreference = 'Stop'
# PowerShell 7.3+ can optionally throw on nonzero native exit status; check it explicitly here.
$PSNativeCommandUseErrorActionPreference = $false
function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    $result = & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program $($Arguments[0]) failed (exit $LASTEXITCODE). See the diagnostic above." }
    return $result
}
function Read-GitHub([string]$Path) {
    # Return $null ONLY on an actual 404; permission or network errors stop the publisher.
    $tempErr = [IO.Path]::GetTempFileName()
    try {
        $oldPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            $out = & gh api --hostname github.com $Path 2>$tempErr
            $code = $LASTEXITCODE
        } finally { $ErrorActionPreference = $oldPreference }
        if ($code -eq 0) { return (($out -join "`n") | ConvertFrom-Json) }
        $message = [IO.File]::ReadAllText($tempErr)
        if ($message -match '\bHTTP 404\b') { return $null }
        throw "GitHub could not read $Path. $message"
    } finally { Remove-Item -LiteralPath $tempErr -ErrorAction SilentlyContinue }
}
Push-Location -LiteralPath $PSScriptRoot
try {
    foreach ($p in @('git','gh')) { if (-not (Get-Command $p -ErrorAction SilentlyContinue)) { throw "Install $p before publishing." } }
    $me = Read-GitHub 'user'
    if (-not $me -or $me.login -ne $Owner) { throw "The GitHub.com login must match -Owner. Sign in with: gh auth login --hostname github.com --git-protocol https --web" }
    $Owner = $me.login
    $target = "$Owner/$Repository"
    $remote = "https://github.com/$target.git"
    $api = "repos/$target"
    $source = Get-Content -LiteralPath './release-manifest.json' -Raw | ConvertFrom-Json
    $paths = @('release-manifest.json')
    foreach ($item in $source.files) {
        $rel = [string]$item.path
        if ($rel -notmatch '^[A-Za-z0-9._/-]+$' -or $rel -match '(^/|//|/$|(^|/)(\.\.?|\.git)(/|$)|^-)') { throw "Unexpected release path: $rel." }
        $info = Get-Item -LiteralPath $rel
        if ($info.PSIsContainer -or ($info.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "Expected a regular file: $rel." }
        if ($info.Length -ne $item.bytes -or (Get-FileHash -LiteralPath $rel -Algorithm SHA256).Hash -ne $item.sha256) { throw "Release checksum failed for $rel. Re-extract the download into a new folder." }
        $paths += $rel
    }
    $marker = '.git/atlas-pages-publisher'
    $resume = Test-Path -LiteralPath $marker -PathType Leaf
    if ($resume) {
        if ((Get-Content -LiteralPath $marker -Raw).Trim() -cne $target) { throw 'This folder was already used to publish to a different repository.' }
        $existingOrigin = Invoke-Checked 'git' @('remote','get-url','origin')
        if (($existingOrigin -join '') -cne $remote) { throw 'The local origin has changed; stopping.' }
        $branch = Invoke-Checked 'git' @('symbolic-ref','--short','HEAD')
        if (($branch -join '') -cne 'main') { throw 'The local branch must be main.' }
    } else {
        $dir = [IO.DirectoryInfo](Get-Item -LiteralPath '.')
        while ($dir) {
            if (Test-Path -LiteralPath (Join-Path $dir.FullName '.git')) { throw 'Extract the ZIP into its own folder outside an existing Git checkout.' }
            $dir = $dir.Parent
        }
    }
    $repo = Read-GitHub $api
    $hadBranches = $false
    if ($repo) {
        if ($repo.full_name -ne $target -or $repo.owner.login -ne $Owner -or $repo.private -or -not $repo.permissions.admin -or $repo.archived -or $repo.fork) { throw 'The destination must be a public, writable repository owned by your signed-in account.' }
        $branches = @(Read-GitHub "$api/branches?per_page=2" | Where-Object { $_ })
        $hadBranches = $branches.Count -gt 0
        if (-not $resume -and (-not $UseExistingEmpty -or $hadBranches)) { throw 'This name is already in use. Choose another -Repository, or pass -UseExistingEmpty for an empty repository that you own.' }
        if ($hadBranches) {
            $head = Invoke-Checked 'git' @('rev-parse','HEAD')
            if ($branches.Count -ne 1 -or $branches[0].name -cne 'main' -or $branches[0].commit.sha -cne ($head -join '')) { throw 'Remote contents differ from this release. No changes were made to the repository.' }
        }
        $pages = Read-GitHub "$api/pages"
        if ($pages -and ($pages.build_type -ne 'legacy' -or $pages.source.branch -ne 'main' -or $pages.source.path -ne '/docs')) { throw 'Pages is configured for another source; stopping.' }
    }
    if (-not $resume) {
        Invoke-Checked 'git' @('init','-b','main') | Out-Host
        Invoke-Checked 'git' @('remote','add','origin',$remote) | Out-Host
        [IO.File]::WriteAllText((Join-Path $PWD $marker), $target)
    }
    if (-not $hadBranches) {
        $pathFile = '.git/atlas-release-paths'
        [IO.File]::WriteAllLines((Join-Path $PWD $pathFile), [string[]]$paths, (New-Object System.Text.UTF8Encoding($false)))
        Invoke-Checked 'git' @('--literal-pathspecs','add',"--pathspec-from-file=$pathFile") | Out-Host
        $tracked = @(Invoke-Checked 'git' @('ls-files'))
        if (Compare-Object ($paths | Sort-Object) ($tracked | Sort-Object)) { throw 'The staged files differ from the release manifest; stopping.' }
        $cachedName = @(Invoke-Checked 'git' @('diff','--cached','--name-only'))
        if ($cachedName.Count) {
            $email = "$($me.id)+$Owner@users.noreply.github.com"
            Invoke-Checked 'git' @('-c',"user.name=$Owner",'-c',"user.email=$email",'commit','-m','Publish CONUS Monthly Atlas v0.8') | Out-Host
        }
        if (-not $repo) {
            Invoke-Checked 'gh' @('api','--hostname','github.com','--method','POST','user/repos','-f',"name=$Repository",'-F','private=false','-F','auto_init=false','-f','description=A monthly atlas of climate, land cover, snow, ice, slope and river flow in the contiguous United States.') | Out-Null
        }
        Invoke-Checked 'git' @('-c','credential.helper=','-c','credential.helper=!gh auth git-credential','push','--set-upstream','origin','main') | Out-Host
    }
    $pages = Read-GitHub "$api/pages"
    if (-not $pages) {
        Invoke-Checked 'gh' @('api','--hostname','github.com','--method','POST',"$api/pages",'-f','build_type=legacy','-f','source[branch]=main','-f','source[path]=/docs') | Out-Null
        $pages = Read-GitHub "$api/pages"
    }
    if (-not $pages -or $pages.build_type -ne 'legacy' -or $pages.source.branch -ne 'main' -or $pages.source.path -ne '/docs') { throw 'Could not verify the Pages source. Check repository Settings > Pages.' }
    $url = [string]$pages.html_url
    Write-Host "Repository: https://github.com/$target"
    Write-Host "GitHub Pages URL: $url"
    $deadline = [DateTime]::UtcNow.AddMinutes(2)
    do {
        try {
            $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10
            if ($response.StatusCode -eq 200 -and $response.Content -match '(?is)<title>[^<]*CONUS Monthly Atlas[^<]*</title>') {
                Write-Host 'Verified: GitHub Pages is serving the atlas.'; return
            }
        } catch { }
        if ([DateTime]::UtcNow -lt $deadline) { Start-Sleep -Seconds 5 }
    } while ([DateTime]::UtcNow -lt $deadline)
    Write-Host "Pages is configured, but the atlas is not verified live yet. Check https://github.com/$target/actions or repository Settings > Pages."
} finally { Pop-Location }
