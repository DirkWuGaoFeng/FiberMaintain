# Full API test script - C++ backend GET endpoints
$base = "http://127.0.0.1:8080"
$pass = 0
$fail = 0

$endpoints = @(
    @{ name = "Health Check"; path = "/health" },
    @{ name = "Fiber Stats Realtime"; path = "/api/v1/fibers/stats/realtime" },
    @{ name = "Fiber Stats Trend"; path = "/api/v1/fibers/stats/trend" },
    @{ name = "All Colored Fibers"; path = "/api/v1/fibers/colored/all" },
    @{ name = "Red Fibers"; path = "/api/v1/fibers/colored?color=RED" },
    @{ name = "Yellow Fibers"; path = "/api/v1/fibers/colored?color=YELLOW" },
    @{ name = "Fiber Connection"; path = "/api/v1/topology/fibers/3" },
    @{ name = "Fiber Scene"; path = "/api/v1/topology/fibers/3/scene" },
    @{ name = "Board Detail"; path = "/api/v1/boards/10003" },
    @{ name = "Board Fibers"; path = "/api/v1/boards/10003/fibers" },
    @{ name = "All Boards"; path = "/api/v1/boards" },
    @{ name = "Fiber Performance"; path = "/api/v1/fibers/3/performance" },
    @{ name = "Fiber Spanloss"; path = "/api/v1/fibers/3/spanloss" },
    @{ name = "Fiber History Perf"; path = "/api/v1/fibers/3/performance/history" },
    @{ name = "Alarms Current All"; path = "/api/v1/alarms/current" },
    @{ name = "Alarms By Board"; path = "/api/v1/alarms/current?board_id=10066" },
    @{ name = "Port Performance"; path = '/api/v1/performance/current?board_id=10003&port_id=1' },
    @{ name = "Port History Perf"; path = '/api/v1/performance/history?board_id=10003&port_id=1' },
    @{ name = "Fibers By Port"; path = '/api/v1/topology/fibers/by_port?board_id=10003&port_id=1' }
)

Write-Host "====== C++ Backend Full GET API Test ======" -ForegroundColor Cyan
Write-Host ""

foreach ($ep in $endpoints) {
    try {
        $uri = "$base$($ep.path)"
        $r = Invoke-WebRequest -Uri $uri -Method GET -UseBasicParsing -TimeoutSec 10
        $code = $r.StatusCode
        $len = $r.Content.Length
        if ($code -eq 200) {
            Write-Host "[PASS] $($ep.name) ($code, ${len}B) - $($ep.path)" -ForegroundColor Green
            $pass++
        } else {
            Write-Host "[FAIL] $($ep.name) ($code) - $($ep.path)" -ForegroundColor Red
            $fail++
        }
    } catch {
        $code = "ERR"
        if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode }
        Write-Host "[FAIL] $($ep.name) ($code) - $($ep.path)" -ForegroundColor Red
        $fail++
    }
}

Write-Host ""
Write-Host "====== Backend Result: $pass PASS, $fail FAIL ======" -ForegroundColor $(if ($fail -eq 0) { "Green" } else { "Yellow" })

# Test via Vite proxy (frontend :5173)
Write-Host ""
Write-Host "====== Vite Proxy Test (frontend :5173 -> backend :8080) ======" -ForegroundColor Cyan
$proxyBase = "http://127.0.0.1:5173"
$proxyEndpoints = @(
    @{ name = "Fiber Stats Realtime (proxy)"; path = "/api/v1/fibers/stats/realtime" },
    @{ name = "All Colored Fibers (proxy)"; path = "/api/v1/fibers/colored/all" },
    @{ name = "Fiber Connection (proxy)"; path = "/api/v1/topology/fibers/3" },
    @{ name = "Alarms Current (proxy)"; path = "/api/v1/alarms/current" },
    @{ name = "Board Detail (proxy)"; path = "/api/v1/boards/10003" },
    @{ name = "Fiber Stats Trend (proxy)"; path = "/api/v1/fibers/stats/trend" },
    @{ name = "Fiber Performance (proxy)"; path = "/api/v1/fibers/3/performance" }
)

$proxyPass = 0
$proxyFail = 0

foreach ($ep in $proxyEndpoints) {
    try {
        $uri = "$proxyBase$($ep.path)"
        $r = Invoke-WebRequest -Uri $uri -Method GET -UseBasicParsing -TimeoutSec 10
        $code = $r.StatusCode
        if ($code -eq 200) {
            Write-Host "[PASS] $($ep.name) ($code) - $($ep.path)" -ForegroundColor Green
            $proxyPass++
        } else {
            Write-Host "[FAIL] $($ep.name) ($code) - $($ep.path)" -ForegroundColor Red
            $proxyFail++
        }
    } catch {
        Write-Host "[FAIL] $($ep.name) - $($ep.path) - $($_.Exception.Message)" -ForegroundColor Red
        $proxyFail++
    }
}

Write-Host ""
Write-Host "====== Proxy Result: $proxyPass PASS, $proxyFail FAIL ======" -ForegroundColor $(if ($proxyFail -eq 0) { "Green" } else { "Yellow" })

# Summary
Write-Host ""
$total = $pass + $proxyPass
$totalFail = $fail + $proxyFail
Write-Host "====== TOTAL: $total PASS, $totalFail FAIL ======" -ForegroundColor $(if ($totalFail -eq 0) { "Green" } else { "Red" })
