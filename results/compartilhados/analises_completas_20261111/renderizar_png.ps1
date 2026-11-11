$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$figures = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'graficos/primitivas.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($figure in $figures) {
    $bitmap = New-Object System.Drawing.Bitmap 2240,1440
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.Clear([System.Drawing.Color]::White)
    $graphics.ScaleTransform(2,2)
    $graphics.SmoothingMode = 'AntiAlias'
    $graphics.TextRenderingHint = 'AntiAliasGridFit'
    foreach ($c in $figure.commands) {
        $color = [System.Drawing.ColorTranslator]::FromHtml($c.color)
        if ($c.kind -eq 'line') {
            $pen = New-Object System.Drawing.Pen $color,([single]$c.width)
            $graphics.DrawLine($pen,[single]$c.x,[single]$c.y,[single]$c.xx,[single]$c.yy)
            $pen.Dispose()
        } else {
            $brush = New-Object System.Drawing.SolidBrush $color
            if ($c.kind -eq 'dot') {
                $graphics.FillEllipse($brush,([single]$c.x-3.5),([single]$c.y-3.5),7,7)
            } else {
                $font = New-Object System.Drawing.Font 'Arial',([single]$c.size),([System.Drawing.FontStyle]::Regular),([System.Drawing.GraphicsUnit]::Pixel)
                $graphics.DrawString([string]$c.text,$font,$brush,[single]$c.x,([single]$c.y-[single]$c.size))
                $font.Dispose()
            }
            $brush.Dispose()
        }
    }
    $bitmap.Save((Join-Path $PSScriptRoot ('graficos/'+$figure.name+'.png')),[System.Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose()
    $bitmap.Dispose()
}
