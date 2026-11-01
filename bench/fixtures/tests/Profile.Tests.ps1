BeforeAll {
    . "$PSScriptRoot/../src/Profile.psm1"
}

Describe "Get-ProfilePath" {
    It "combine le repertoire de profil et le nom" {
        $path = Get-ProfilePath -Name "Microsoft.PowerShell_profile.ps1"
        $path | Should -Not -BeNullOrEmpty
        $path | Should -BeLike "*Microsoft.PowerShell_profile.ps1"
    }
}

Describe "Test-ProfileExists" {
    It "renvoie faux pour un nom absent" {
        Test-ProfileExists -Name "definitivement-absent-$$.ps1" | Should -BeFalse
    }
}

Describe "Get-Profile" {
    It "renvoie $null si le fichier n'existe pas" {
        Get-Profile -Name "definitivement-absent-$$.ps1" | Should -BeNullOrEmpty
    }

    It "lance une erreur explicite si la lecture echoue" {
        { Get-Profile -Name "verrouille-$$.ps1" -ErrorAction Stop } | Should -Throw
    }
}

Describe "Set-Profile" {
    It "ecrit le contenu et renvoie le chemin" {
        $name = "temp-osiris-bench-$$.ps1"
        $written = Set-Profile -Name $name -Content "# test"
        $written | Should -Not -BeNullOrEmpty
        Test-ProfileExists -Name $name | Should -BeTrue
    }
}
