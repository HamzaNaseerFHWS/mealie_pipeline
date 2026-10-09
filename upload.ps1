# Usage: $env:MEALIE_URL="http://host:port"; $env:MEALIE_TOKEN="..."; ./upload.ps1 [recipe.json]
param([string]$File = "$PSScriptRoot\recipe.json")
$base = $env:MEALIE_URL.TrimEnd('/')
$h = @{ Authorization = "Bearer $env:MEALIE_TOKEN" }
$r = Get-Content $File -Raw -Encoding UTF8 | ConvertFrom-Json

# 1. auth check
$me = Invoke-RestMethod "$base/api/users/self" -Headers $h
"Authenticated as: $($me.username)"

# 2. create empty recipe -> slug
$slug = Invoke-RestMethod "$base/api/recipes" -Method Post -Headers $h -ContentType 'application/json' -Body (@{ name = $r.name } | ConvertTo-Json)
"Created slug: $slug"

# 3. fetch, fill, patch
$rec = Invoke-RestMethod "$base/api/recipes/$slug" -Headers $h
$rec.description = $r.description
$rec.orgURL = $r.orgURL
$rec.prepTime = $r.prepTime
$rec.performTime = $r.performTime
$rec.recipeYield = $r.recipeYield
$rec.recipeIngredient = @($r.recipeIngredient | ForEach-Object { @{ note = $_ } })
$rec.recipeInstructions = @($r.recipeInstructions | ForEach-Object { @{ text = $_ } })
$body = $rec | ConvertTo-Json -Depth 20
Invoke-RestMethod "$base/api/recipes/$slug" -Method Patch -Headers $h -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body)) | Out-Null
"Done: $base/g/home/r/$slug"
