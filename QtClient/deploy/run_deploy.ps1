# windeployqt 打包脚本（预留，首版在开发环境直接运行）
# 用法：在 "Qt 6.10.0 (MinGW 13.1.0) 64-bit" 命令行工具中，cd 到构建目录后运行本脚本。
# 设计意图：把 Qt 运行时 DLL、plugins、QSS 依赖一次性拷到发布目录，
#           路径变量允许通过参数覆盖，方便后续 CI 复用。

param(
    [string]$Exe = ".\build\FiberMonitorClient.exe",
    [string]$QtDir = "G:\Software\Qt\6.10.0\mingw_64"
)

$windeployqt = Join-Path $QtDir "bin\windeployqt.exe"

if (-not (Test-Path $Exe)) {
    Write-Error "找不到可执行文件：$Exe（请先用 cmake --build 构建）"
    exit 1
}
if (-not (Test-Path $windeployqt)) {
    Write-Error "找不到 windeployqt：$windeployqt（请检查 -QtDir 参数）"
    exit 1
}

# --mingw 指向 MinGW 运行时；--release 去除调试依赖；--no-translations 精简体积
& $windeployqt --mingw --release --no-translations --no-system-software-on-dll $Exe
if ($LASTEXITCODE -ne 0) {
    Write-Error "windeployqt 执行失败，退出码 $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "打包完成：$([IO.Path]::GetDirectoryName((Resolve-Path $Exe)))" -ForegroundColor Green
