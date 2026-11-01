<#
.SYNOPSIS
    Gestion des profils PowerShell (fixture de benchmark OSIRIS).
.DESCRIPTION
    Module realiste d'uneertaliers de fonctions. Contient un bug volontaire :
    Get-Profile n'echoue pas explicitement quand la lecture du fichier leve
    une erreur, parce que -ErrorAction Stop n'est pas passe a Get-Content.
.NOTES
    La taille du fichier est representative d'un module de production
    (environ 200 lignes), car c'est la taille ou le mecanisme OSIRIS
    commence a etre rentable.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

$script:DefaultProfileNames = @(
    'Microsoft.PowerShell_profile.ps1'
    'Microsoft.PowerShell_profile.psm1'
)

$script:ProfileCache = @{}

# ---------------------------------------------------------------------------
# Fonctions internes
# ---------------------------------------------------------------------------

function Get-ProfileBaseDirectory {
    <#
    .SYNOPSIS
        Retourne le repertoire de base des profils.
    #>
    [CmdletBinding()]
    param()

    if ($env:PROFILE) {
        return (Split-Path -Parent $env:PROFILE)
    }

    if ($env:HOME) {
        return $env:HOME
    }

    return [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
}

function Test-ProfileName {
    <#
    .SYNOPSIS
        Valide qu'un nom de profil est utilisable.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string]$Name
    )

    if ([string]::IsNullOrWhiteSpace($Name)) {
        return $false
    }

    if ($Name.IndexOfAny([System.IO.Path]::GetInvalidFileNameChars()) -ge 0) {
        return $false
    }

    return $true
}

function Clear-ProfileCache {
    <#
    .SYNOPSIS
        Vide le cache de profils en memoire.
    #>
    [CmdletBinding()]
    param()

    $script:ProfileCache.Clear()
}

# ---------------------------------------------------------------------------
# Fonctions publiques
# ---------------------------------------------------------------------------

function Get-ProfilePath {
    <#
    .SYNOPSIS
        Construit le chemin complet d'un profil.
    .PARAMETER Name
        Nom du fichier de profil.
    .EXAMPLE
        Get-ProfilePath -Name 'profile.ps1'
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory)]
        [string]$Name
    )

    if (-not (Test-ProfileName -Name $Name)) {
        throw "Nom de profil invalide : '$Name'"
    }

    $base = Get-ProfileBaseDirectory
    return [System.IO.Path]::Combine($base, $Name)
}

function Get-DefaultProfileName {
    <#
    .SYNOPSIS
        Retourne le nom du profil par defaut de la session courante.
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [switch]$IncludeModule
    )

    if ($IncludeModule) {
        return $script:DefaultProfileNames[1]
    }

    return $script:DefaultProfileNames[0]
}

function Test-ProfileExists {
    <#
    .SYNOPSIS
        Indique si un profil existe sur le disque.
    #>
    [CmdletBinding()]
    [OutputType([bool])]
    param(
        [Parameter(Mandatory)]
        [string]$Name
    )

    $path = Get-ProfilePath -Name $Name
    return (Test-Path -LiteralPath $path -PathType Leaf)
}

function Get-Profile {
    <#
    .SYNOPSIS
        Lit le contenu d'un profil.
    .DESCRIPTION
        Retourne $null si le profil n'existe pas.
    .NOTES
        BUG VOLONTAIRE : Get-Content est appele sans -ErrorAction Stop,
        donc une erreur de lecture est silencieuse et le module continue
        comme si le profil etait vide.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Name
    )

    if ($script:ProfileCache.ContainsKey($Name)) {
        return $script:ProfileCache[$Name]
    }

    $path = Get-ProfilePath -Name $Name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        return $null
    }

    # BUG : sans -ErrorAction Stop, une erreur de lecture est silencieuse
    $content = Get-Content -LiteralPath $path -Raw
    $script:ProfileCache[$Name] = $content

    return $content
}

function Set-Profile {
    <#
    .SYNOPSIS
        Ecrit un profil sur le disque.
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [AllowEmptyString()]
        [string]$Content
    )

    $path = Get-ProfilePath -Name $Name
    $directory = Split-Path -Parent $path

    if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }

    Set-Content -LiteralPath $path -Value $Content -Encoding utf8
    $script:ProfileCache[$Name] = $Content

    return $path
}

function Remove-Profile {
    <#
    .SYNOPSIS
        Supprime un profil du disque.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Name
    )

    $path = Get-ProfilePath -Name $Name
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        Remove-Item -LiteralPath $path -Force
    }

    $script:ProfileCache.Remove($Name)
}

function Get-ProfileList {
    <#
    .SYNOPSIS
        Liste tous les profils presents dans le repertoire de base.
    #>
    [CmdletBinding()]
    [OutputType([object[]])]
    param()

    $base = Get-ProfileBaseDirectory
    if (-not (Test-Path -LiteralPath $base -PathType Container)) {
        return @()
    }

    $items = @()
    foreach ($file in Get-ChildItem -LiteralPath $base -File -ErrorAction SilentlyContinue) {
        $items += [PSCustomObject]@{
            Name         = $file.Name
            Path         = $file.FullName
            SizeBytes    = $file.Length
            LastWriteUtc = $file.LastWriteTimeUtc
        }
    }

    return $items
}

function Measure-Profile {
    <#
    .SYNOPSIS
        Mesure la taille et le nombre de lignes d'un profil.
    #>
    [CmdletBinding()]
    [OutputType([hashtable])]
    param(
        [Parameter(Mandatory)]
        [string]$Name
    )

    $path = Get-ProfilePath -Name $Name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        return @{
            Exists      = $false
            SizeBytes   = 0
            LineCount   = 0
            LastWriteUtc = $null
        }
    }

    $item = Get-Item -LiteralPath $path
    $lines = (Get-Content -LiteralPath $path | Measure-Object -Line).Lines

    return @{
        Exists       = $true
        SizeBytes    = $item.Length
        LineCount    = $lines
        LastWriteUtc = $item.LastWriteTimeUtc
    }
}

function Backup-Profile {
    <#
    .SYNOPSIS
        Sauvegarde un profil avec un suffixe horodate.
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory)]
        [string]$Name
    )

    $content = Get-Profile -Name $Name
    if ($null -eq $content) {
        throw "Le profil '$Name' n'existe pas."
    }

    $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmss')
    $backupName = "$Name.$stamp.bak"
    $backupPath = Get-ProfilePath -Name $backupName

    Set-Content -LiteralPath $backupPath -Value $content -Encoding utf8
    return $backupPath
}

function Restore-Profile {
    <#
    .SYNOPSIS
        Restaure un profil depuis une sauvegarde.
    #>
    [CmdletBinding()]
    [OutputType([string])]
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [string]$BackupName
    )

    $backupPath = Get-ProfilePath -Name $BackupName
    if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf)) {
        throw "La sauvegarde '$BackupName' est introuvable."
    }

    $content = Get-Content -LiteralPath $backupPath -Raw
    return (Set-Profile -Name $Name -Content $content)
}

function Invoke-Profile {
    <#
    .SYNOPSIS
        Execute un profil dans la session courante.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Name
    )

    $path = Get-ProfilePath -Name $Name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        return $false
    }

    . $path
    return $true
}

Export-ModuleMember -Function Get-ProfilePath, Get-DefaultProfileName, Test-ProfileExists,
Get-Profile, Set-Profile, Remove-Profile, Get-ProfileList, Measure-Profile,
Backup-Profile, Restore-Profile, Invoke-Profile
