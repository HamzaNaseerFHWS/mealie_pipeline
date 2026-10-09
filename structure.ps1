# Usage: $env:MEALIE_URL=...; $env:MEALIE_TOKEN=...; ./structure.ps1 [slug]
param([string]$Slug = "chatpata-bhindi-aloo")
$base = $env:MEALIE_URL.TrimEnd('/')
$h = @{ Authorization = "Bearer $env:MEALIE_TOKEN" }
function Api($m, $p, $b) {
    $a = @{ Uri = "$base$p"; Method = $m; Headers = $h; ContentType = 'application/json; charset=utf-8' }
    if ($b) { $a.Body = [Text.Encoding]::UTF8.GetBytes(($b | ConvertTo-Json -Depth 20)) }
    Invoke-RestMethod @a
}

# Hand-parsed ingredients: qty, unit (name|abbr), food, note
$items = @(
    @(250,  'gram',       'okra',                    'lady finger / bhindi'),
    @(1,    $null,        'potato',                  ''),
    @($null,$null,        'water',                   'as required'),
    @(2,    $null,        'onion',                   'small'),
    @(2,    'tablespoon', 'mustard oil',             ''),
    @(0.5,  'teaspoon',   'cumin seeds',             ''),
    @(1,    'tablespoon', 'garlic',                  'roughly chopped'),
    @(2,    $null,        'green chilli',            'chopped'),
    @(0.25, 'teaspoon',   'asafoetida',              ''),
    @(0.25, 'teaspoon',   'turmeric powder',         ''),
    @(1,    'teaspoon',   'coriander powder',        ''),
    @(0.5,  'teaspoon',   'Kashmiri red chilli powder', ''),
    @(1,    'teaspoon',   'cumin powder',            ''),
    @(1,    'teaspoon',   'dry mango powder',        'amchur'),
    @(1,    'teaspoon',   'kasuri methi',            ''),
    @($null,$null,        'salt',                    'to taste'),
    @(1,    'pinch',      'garam masala',            ''),
    @(1,    'handful',    'fresh coriander',         'chopped')
)
$unitAlias = @{ gram='g'; tablespoon='tbsp'; teaspoon='tsp' }

$units = (Api GET '/api/units?perPage=-1').items
$foods = (Api GET '/api/foods?perPage=-1').items
function Norm($s) { "$s".ToLower().Trim() }

function GetUnit($name) {
    $n = Norm $name
    $u = $script:units | Where-Object { (Norm $_.name) -eq $n -or (Norm $_.abbreviation) -eq $n -or (Norm $_.pluralName) -eq $n } | Select-Object -First 1
    if (-not $u) {
        $u = Api POST '/api/units' @{ name = $name; abbreviation = "$($unitAlias[$name])"; useAbbreviation = [bool]$unitAlias[$name] }
        $script:units += $u; "  created unit: $name" | Write-Host
    }
    $u
}
function GetFood($name) {
    $n = Norm $name
    $f = $script:foods | Where-Object { (Norm $_.name) -eq $n -or (Norm $_.pluralName) -eq $n } | Select-Object -First 1
    if (-not $f) {
        $f = Api POST '/api/foods' @{ name = $name }
        $script:foods += $f; "  created food: $name" | Write-Host
    }
    $f
}

$ing = foreach ($i in $items) {
    $qty, $un, $fd, $note = $i
    $u = if ($un) { GetUnit $un } else { $null }
    $f = GetFood $fd
    @{
        quantity = if ($null -ne $qty) { [double]$qty } else { 0 }
        unit = if ($u) { @{ id = $u.id; name = $u.name } } else { $null }
        food = @{ id = $f.id; name = $f.name }
        note = $note
        originalText = $null
        referenceId = [guid]::NewGuid().ToString()
    }
}

$rec = Api GET "/api/recipes/$Slug"
$rec.recipeIngredient = @($ing)
Api PATCH "/api/recipes/$Slug" $rec | Out-Null

$chk = Api GET "/api/recipes/$Slug"
$chk.recipeIngredient | ForEach-Object { "{0,-6} {1,-11} {2,-26} {3}" -f $_.quantity, $_.unit.name, $_.food.name, $_.note }
