param([string]$SdkDirectory = '', [string]$OutputDirectory = '')
$ErrorActionPreference = 'Stop'
$sourceDirectory = Split-Path -Parent $PSScriptRoot
$appDirectory = if ($OutputDirectory) { [IO.Path]::GetFullPath($OutputDirectory) } else { $sourceDirectory }
New-Item -ItemType Directory -Force -Path $appDirectory | Out-Null
$packageVersion = '1.0.4191.47'
if (!$SdkDirectory) {
    $buildDirectory = Join-Path $PSScriptRoot '.build'
    New-Item -ItemType Directory -Force -Path $buildDirectory | Out-Null
    $SdkDirectory = Join-Path $buildDirectory 'webview2'
    if (!(Test-Path -LiteralPath (Join-Path $SdkDirectory 'lib\net462\Microsoft.Web.WebView2.Core.dll'))) {
        $packagePath = Join-Path $buildDirectory 'webview2.zip'
        Invoke-WebRequest -Uri "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/$packageVersion/microsoft.web.webview2.$packageVersion.nupkg" -OutFile $packagePath
        Expand-Archive -LiteralPath $packagePath -DestinationPath $SdkDirectory -Force
    }
}
$SdkDirectory = (Resolve-Path -LiteralPath $SdkDirectory).Path
foreach ($library in @('Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.WinForms.dll')) {
    Copy-Item -LiteralPath (Join-Path $SdkDirectory "lib\net462\$library") -Destination $appDirectory -Force
}
Copy-Item -LiteralPath (Join-Path $SdkDirectory 'runtimes\win-x64\native\WebView2Loader.dll') -Destination $appDirectory -Force
Copy-Item -LiteralPath (Join-Path $SdkDirectory 'LICENSE.txt') -Destination (Join-Path $appDirectory 'WebView2-LICENSE.txt') -Force
Copy-Item -LiteralPath (Join-Path $SdkDirectory 'NOTICE.txt') -Destination (Join-Path $appDirectory 'WebView2-NOTICE.txt') -Force
Add-Type -AssemblyName System.Drawing
$iconPath = Join-Path $appDirectory 'Meeting Studio.ico'
$images = @()
foreach ($size in @(16, 24, 32, 48, 64, 128, 256)) {
    $bitmap = New-Object System.Drawing.Bitmap($size, $size)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.Clear([System.Drawing.Color]::Transparent)
    $background = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(29, 94, 79))
    $wave = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(249, 245, 231), ($size * 0.07))
    $wave.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $wave.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $shape = New-Object System.Drawing.Drawing2D.GraphicsPath
    $edge = $size * 0.06
    $corner = $size * 0.35
    $far = $size - $edge - $corner
    $shape.AddArc($edge, $edge, $corner, $corner, 180, 90)
    $shape.AddArc($far, $edge, $corner, $corner, 270, 90)
    $shape.AddArc($far, $far, $corner, $corner, 0, 90)
    $shape.AddArc($edge, $far, $corner, $corner, 90, 90)
    $shape.CloseFigure()
    $graphics.FillPath($background, $shape)
    $heights = @(0.18, 0.36, 0.55, 0.36, 0.18)
    for ($index = 0; $index -lt 5; $index++) {
        $x = [single]($size * (0.24 + $index * 0.13))
        $half = $size * $heights[$index] / 2
        $graphics.DrawLine($wave, $x, [single]($size / 2 - $half), $x, [single]($size / 2 + $half))
    }
    $png = New-Object System.IO.MemoryStream
    $bitmap.Save($png, [System.Drawing.Imaging.ImageFormat]::Png)
    $images += ,@{ Size = $size; Bytes = $png.ToArray() }
    $png.Dispose(); $shape.Dispose(); $wave.Dispose(); $background.Dispose(); $graphics.Dispose(); $bitmap.Dispose()
}
$stream = [System.IO.File]::Create($iconPath)
$writer = New-Object System.IO.BinaryWriter($stream)
try {
    $writer.Write([uint16]0); $writer.Write([uint16]1); $writer.Write([uint16]$images.Count)
    $offset = 6 + 16 * $images.Count
    foreach ($image in $images) {
        $iconSize = if ($image.Size -eq 256) { 0 } else { $image.Size }
        $writer.Write([byte]$iconSize); $writer.Write([byte]$iconSize)
        $writer.Write([byte]0); $writer.Write([byte]0)
        $writer.Write([uint16]1); $writer.Write([uint16]32)
        $writer.Write([uint32]$image.Bytes.Length); $writer.Write([uint32]$offset)
        $offset += $image.Bytes.Length
    }
    foreach ($image in $images) { $writer.Write([byte[]]$image.Bytes) }
} finally { $writer.Dispose(); $stream.Dispose() }
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$arguments = @('/nologo', '/target:winexe', '/platform:x64', '/optimize+',
    "/out:$(Join-Path $appDirectory 'Meeting Studio.exe')",
    "/win32icon:$iconPath", "/win32manifest:$(Join-Path $PSScriptRoot 'app.manifest')",
    '/reference:System.dll', '/reference:System.Core.dll', '/reference:System.Drawing.dll',
    '/reference:System.Windows.Forms.dll', '/reference:System.Net.Http.dll', '/reference:System.Web.Extensions.dll',
    "/reference:$(Join-Path $appDirectory 'Microsoft.Web.WebView2.Core.dll')",
    "/reference:$(Join-Path $appDirectory 'Microsoft.Web.WebView2.WinForms.dll')",
    (Join-Path $PSScriptRoot 'MeetingStudio.cs'), (Join-Path $PSScriptRoot 'ShortcutInstaller.cs'))
& $compiler @arguments
if ($LASTEXITCODE -ne 0) { throw 'The desktop app did not compile.' }
if ($appDirectory -ne $sourceDirectory) {
    Copy-Item -LiteralPath (Join-Path $sourceDirectory 'Meeting Studio.exe.config') -Destination $appDirectory -Force
}
Write-Output 'Built Meeting Studio.exe with its icon and local WebView2 libraries.'
