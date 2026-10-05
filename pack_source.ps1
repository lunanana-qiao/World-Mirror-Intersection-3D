# 打包源码（排除 venv、密码、超大文件）
$root = $PSScriptRoot
$outZip = Join-Path (Split-Path $root -Parent) "intersection_project_source.zip"

if (Test-Path $outZip) { Remove-Item $outZip -Force }

$items = @(
    "app.py", "agent.py", "autodl_client.py",
    "config.example.toml", "requirements.txt",
    "start_share.bat", ".gitignore",
    "软件说明书.md", "验收表-检查验收项目和内容.txt"
)

$temp = Join-Path $env:TEMP "intersection_project_pack"
if (Test-Path $temp) { Remove-Item $temp -Recurse -Force }
New-Item -ItemType Directory -Path $temp | Out-Null

foreach ($item in $items) {
    $src = Join-Path $root $item
    if (Test-Path $src) { Copy-Item $src $temp }
}

# 示例照片：只打包前 5 张，避免压缩包过大
$photoDest = Join-Path $temp "photos"
New-Item -ItemType Directory -Path $photoDest | Out-Null
Get-ChildItem (Join-Path $root "photos") -File | Select-Object -First 5 | Copy-Item -Destination $photoDest

# 说明文件
@"
源码包说明
==========
1. 解压后请先阅读 软件说明书.md
2. 安装：python -m venv venv && .\venv\Scripts\activate && pip install -r requirements.txt
3. 启动：streamlit run app.py
4. config.toml 含密码，未包含在压缩包内，请自行 copy config.example.toml 后填写
5. output/gaussians.ply 体积较大（约 500MB），未包含，演示请使用演示模式或自行放置
"@ | Out-File (Join-Path $temp "README.txt") -Encoding utf8

Compress-Archive -Path "$temp\*" -DestinationPath $outZip -Force
Remove-Item $temp -Recurse -Force

Write-Host "已生成: $outZip"
