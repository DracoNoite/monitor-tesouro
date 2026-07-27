<#
    disparar.ps1 -- dispara o monitor agora, sem esperar o cron.

    Serve para duas coisas:
      1. conferir se o token do GitHub funciona ANTES de coloca-lo no cron
         externo (la, um token errado vira um job silenciosamente quebrado)
      2. rodar uma verificacao manual a qualquer momento

    O token vem da variavel de ambiente GITHUB_TOKEN ou do arquivo
    token-github.txt na raiz. Esse arquivo esta no .gitignore. O token nunca e
    impresso na tela, nem em caso de erro.

    Uso:
        .\disparar.ps1
        .\disparar.ps1 -Repo outro/repositorio -Evento verificar
#>

[CmdletBinding()]
param(
    [string]$Repo   = "DracoNoite/monitor-tesouro",
    [string]$Evento = "verificar"
)

$ErrorActionPreference = "Stop"

# O PowerShell 5.1 ainda negocia TLS 1.0 por padrao em algumas maquinas, e a
# API do GitHub recusa. Sem esta linha o erro que aparece e "conexao fechada",
# que nao ajuda ninguem a descobrir a causa.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$arquivoToken = Join-Path $PSScriptRoot "token-github.txt"

$token = $env:GITHUB_TOKEN
if ([string]::IsNullOrWhiteSpace($token) -and (Test-Path $arquivoToken)) {
    $token = (Get-Content $arquivoToken -Raw).Trim()
}

if ([string]::IsNullOrWhiteSpace($token)) {
    Write-Host ""
    Write-Host "  Nenhum token encontrado."
    Write-Host ""
    Write-Host "  Crie um token fine-grained em:"
    Write-Host "    https://github.com/settings/personal-access-tokens/new"
    Write-Host "  com acesso apenas ao repositorio $Repo e a permissao"
    Write-Host "  Contents: Read and write."
    Write-Host ""
    Write-Host "  Depois grave o token em token-github.txt (na raiz do projeto)."
    Write-Host ""
    exit 1
}

$url = "https://api.github.com/repos/$Repo/dispatches"

$cabecalhos = @{
    "Accept"               = "application/vnd.github+json"
    "Authorization"        = "Bearer $token"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent"           = "MonitorTesouro/1.0"
}

$corpo = "{""event_type"":""$Evento""}"

Write-Host ""
Write-Host "  POST $url"
Write-Host "  evento: $Evento"
Write-Host ""

try {
    Invoke-RestMethod -Uri $url -Method Post -Headers $cabecalhos `
        -Body $corpo -ContentType "application/json" -TimeoutSec 30 | Out-Null
}
catch {
    $codigo = 0
    if ($_.Exception.Response) { $codigo = [int]$_.Exception.Response.StatusCode }

    Write-Host "  FALHOU (HTTP $codigo)" -ForegroundColor Red
    Write-Host ""

    switch ($codigo) {
        401 { Write-Host "  O token nao foi aceito: esta expirado, foi revogado ou veio truncado." }
        403 { Write-Host "  Token valido, mas sem permissao. Falta Contents: Read and write." }
        404 {
            # Vale explicar: a API responde 404 (e nao 403) quando o token nao
            # enxerga o repositorio, de proposito, para nao revelar a existencia
            # de repos privados. Sem este aviso, a gente sai procurando erro de
            # digitacao no nome do repositorio, que costuma estar certo.
            Write-Host "  404 aqui quase nunca e nome errado do repositorio."
            Write-Host "  A API devolve 404 tambem quando o token nao tem acesso a ele."
            Write-Host "  Confira: o token foi criado para $Repo e tem Contents: Read and write?"
        }
        422 { Write-Host "  O GitHub recusou o corpo do pedido. O evento '$Evento' bate com o types: do workflow?" }
        default { Write-Host "  $($_.Exception.Message)" }
    }
    Write-Host ""
    exit 1
}

Write-Host "  OK -- o GitHub aceitou o gatilho (HTTP 204)." -ForegroundColor Green
Write-Host ""
Write-Host "  Atencao: 204 quer dizer 'recebi o pedido', nao 'o monitor rodou'."
Write-Host "  Veja a execucao em:"
Write-Host "    https://github.com/$Repo/actions"
Write-Host ""
