<#
.SYNOPSIS
  PowerShell equivalent of the Makefile targets for native Windows development.
.EXAMPLE
  ./scripts/make.ps1 install
  ./scripts/make.ps1 run-local
#>

param(
    [Parameter(Position = 0, Mandatory = $true)]
    [string]$Target,

    [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

switch ($Target) {
    "install" {
        uv sync
    }
    "install-dev" {
        uv sync --dev
    }
    "run-local" {
        Push-Location backend
        try { uv run uvicorn api.main_local:app --host 0.0.0.0 --port 8000 --reload }
        finally { Pop-Location }
    }
    "test" {
        Push-Location backend
        try { uv run pytest tests/ -v --timeout=60 }
        finally { Pop-Location }
    }
    "lint" {
        Push-Location backend
        try {
            uv run ruff check .
            uv run mypy . --ignore-missing-imports
        }
        finally { Pop-Location }
    }
    "format" {
        Push-Location backend
        try {
            uv run ruff format .
            uv run ruff check . --fix
        }
        finally { Pop-Location }
    }
    default {
        Write-Error "Unknown target '$Target'. Valid targets: install, install-dev, run-local, test, lint, format"
        exit 1
    }
}
