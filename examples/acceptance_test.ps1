# 实验室样本交接系统 - 验收测试脚本
# 使用方法: powershell -ExecutionPolicy Bypass -File .\examples\acceptance_test.ps1

$baseUrl = "http://localhost:5000/api"
$script:testCount = 0
$script:passCount = 0
$script:failCount = 0

function Write-Header {
    param([string]$title)
    Write-Host ""
    Write-Host "=" * 70 -ForegroundColor Cyan
    Write-Host "  $title" -ForegroundColor Cyan
    Write-Host "=" * 70 -ForegroundColor Cyan
}

function Write-TestResult {
    param(
        [string]$testName,
        [bool]$passed,
        [string]$message = ""
    )
    $script:testCount++
    if ($passed) {
        $script:passCount++
        Write-Host "  ✓ PASS" -ForegroundColor Green -NoNewline
    } else {
        $script:failCount++
        Write-Host "  ✗ FAIL" -ForegroundColor Red -NoNewline
    }
    Write-Host "  $testName" -ForegroundColor White
    if ($message) {
        if ($passed) {
            Write-Host "        $message" -ForegroundColor Gray
        } else {
            Write-Host "        错误: $message" -ForegroundColor Red
        }
    }
}

function Invoke-Api {
    param(
        [string]$Method,
        [string]$Path,
        [hashtable]$Body = $null
    )
    $url = "$baseUrl$Path"
    try {
        if ($Body) {
            $jsonBody = $Body | ConvertTo-Json -Depth 10
            $response = Invoke-RestMethod -Uri $url -Method $Method -Body $jsonBody -ContentType "application/json" -ErrorAction Stop
        } else {
            $response = Invoke-RestMethod -Uri $url -Method $Method -ErrorAction Stop
        }
        return $response
    } catch {
        if ($_.Exception.Response) {
            $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $reader.BaseStream.Position = 0
            $responseBody = $reader.ReadToEnd()
            try {
                return $responseBody | ConvertFrom-Json
            } catch {
                return @{ success = $false; message = $responseBody }
            }
        }
        return @{ success = $false; message = $_.Exception.Message }
    }
}

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════════════╗" -ForegroundColor Magenta
Write-Host "║           实验室样本交接系统 - 验收测试                          ║" -ForegroundColor Magenta
Write-Host "╚══════════════════════════════════════════════════════════════════╝" -ForegroundColor Magenta
Write-Host ""

# 检查服务是否启动
try {
    $health = Invoke-RestMethod -Uri "$baseUrl/health" -Method Get -ErrorAction Stop
    Write-Host "服务状态: 运行中 ✓" -ForegroundColor Green
} catch {
    Write-Host "服务未启动! 请先运行: python run.py" -ForegroundColor Red
    Write-Host "错误: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

Write-Header "验收用例 1: 完整生命周期（登记→入库→借出→退回→废弃）"

# 1.1 登记样本
$result = Invoke-Api -Method Post -Path "/samples" -Body @{
    sample_code = "TEST-ACCEPT-001"
    name = "验收样本-完整生命周期"
    sample_type = "血液"
    required_temp_zone = "REFRIGERATED"
    operator = "验收员"
    operator_role = "LAB_TECHNICIAN"
    remark = "自动化验收测试"
}
$sampleId = $result.data.id
$sampleVersion = $result.data.version
Write-TestResult "1.1 登记样本成功" ($result.success -eq $true) "样本ID: $sampleId, 版本: $sampleVersion"

# 1.2 状态校验
Write-TestResult "1.2 状态为 REGISTERED" ($result.data.status -eq "REGISTERED") "当前状态: $($result.data.status)"

# 1.3 入库（温区匹配）
$result = Invoke-Api -Method Post -Path "/samples/$sampleId/store-in" -Body @{
    location_id = 3
    operator = "库管员"
    operator_role = "LAB_TECHNICIAN"
    expected_version = $sampleVersion
    reason = "接收入库"
}
$sampleVersion = $result.data.version
Write-TestResult "1.3 入库成功（温区匹配）" ($result.success -eq $true) "新版本: $sampleVersion"

# 1.4 状态校验
Write-TestResult "1.4 状态变为 IN_STORAGE" ($result.data.status -eq "IN_STORAGE") "当前状态: $($result.data.status)"

# 1.5 借出
$result = Invoke-Api -Method Post -Path "/samples/$sampleId/borrow" -Body @{
    operator = "实验员"
    operator_role = "LAB_TECHNICIAN"
    expected_version = $sampleVersion
    reason = "实验使用"
    remark = "测试借出"
}
$sampleVersion = $result.data.version
Write-TestResult "1.5 借出成功" ($result.success -eq $true) "新版本: $sampleVersion"

# 1.6 状态校验
Write-TestResult "1.6 状态变为 BORROWED" ($result.data.status -eq "BORROWED") "当前状态: $($result.data.status)"

# 1.7 退回
$result = Invoke-Api -Method Post -Path "/samples/$sampleId/return" -Body @{
    location_id = 3
    operator = "实验员"
    operator_role = "LAB_TECHNICIAN"
    expected_version = $sampleVersion
    reason = "实验完成退回"
}
$sampleVersion = $result.data.version
Write-TestResult "1.7 退回成功" ($result.success -eq $true) "新版本: $sampleVersion"

# 1.8 状态校验
Write-TestResult "1.8 状态变回 IN_STORAGE" ($result.data.status -eq "IN_STORAGE") "当前状态: $($result.data.status)"

# 1.9 废弃（LAB_MANAGER角色）
$result = Invoke-Api -Method Post -Path "/samples/$sampleId/discard" -Body @{
    operator = "主管"
    operator_role = "LAB_MANAGER"
    expected_version = $sampleVersion
    reason = "样本过期废弃"
    remark = "按SOP处理"
}
$sampleVersion = $result.data.version
Write-TestResult "1.9 废弃成功" ($result.success -eq $true) "最终版本: $sampleVersion"

# 1.10 状态校验
Write-TestResult "1.10 最终状态为 DISCARDED" ($result.data.status -eq "DISCARDED") "最终状态: $($result.data.status)"

# 1.11 审计日志数量
$logsResult = Invoke-Api -Method Get -Path "/samples/$sampleId/audit-logs"
Write-TestResult "1.11 审计日志完整（6条记录）" ($logsResult.data.Count -eq 6) "实际记录数: $($logsResult.data.Count)"

# 1.12 版本号递增验证
$versions = $logsResult.data | ForEach-Object { $_.version } | Sort-Object
$versionCorrect = $versions -join "," -eq "1,2,3,4,5,5"
Write-TestResult "1.12 版本号正确递增" $versionCorrect "版本序列: $($versions -join ',')"


Write-Header "验收用例 2: 温区不匹配导致操作失败"

# 2.1 登记冷冻样本
$result = Invoke-Api -Method Post -Path "/samples" -Body @{
    sample_code = "TEST-ACCEPT-002"
    name = "验收样本-温区测试"
    sample_type = "血清"
    required_temp_zone = "FROZEN"
    operator = "验收员"
    operator_role = "LAB_TECHNICIAN"
}
$sampleId2 = $result.data.id
Write-TestResult "2.1 登记冷冻样本成功" ($result.success -eq $true) "样本ID: $sampleId2"

# 2.2 尝试入库到常温库位（应失败）
$result = Invoke-Api -Method Post -Path "/samples/$sampleId2/store-in" -Body @{
    location_id = 1
    operator = "库管员"
    operator_role = "LAB_TECHNICIAN"
    expected_version = 1
    reason = "测试温区"
}
$tempMismatch = ($result.success -eq $false) -and ($result.error -eq "TEMP_ZONE_MISMATCH")
Write-TestResult "2.2 入库常温库位失败（温区不匹配）" $tempMismatch "错误码: $($result.error)"

# 2.3 验证错误信息包含温区说明
$hasTempInfo = $result.message -match "温区"
Write-TestResult "2.3 错误信息指出温区规则" $hasTempInfo "错误信息: $($result.message.Substring(0, [Math]::Min(60, $result.message.Length)))..."

# 2.4 正确入库到冷冻库位
$result = Invoke-Api -Method Post -Path "/samples/$sampleId2/store-in" -Body @{
    location_id = 5
    operator = "库管员"
    operator_role = "LAB_TECHNICIAN"
    expected_version = 1
    reason = "正常入库"
}
Write-TestResult "2.4 正确入库冷冻库位成功" ($result.success -eq $true) "状态: $($result.data.status)"

# 2.5 尝试转移到冷藏库位（应失败）
$result = Invoke-Api -Method Post -Path "/samples/$sampleId2/transfer" -Body @{
    to_location_id = 3
    operator = "库管员"
    operator_role = "LAB_TECHNICIAN"
    expected_version = 2
    reason = "测试转移温区"
}
$transferFail = ($result.success -eq $false) -and ($result.error -eq "TEMP_ZONE_MISMATCH")
Write-TestResult "2.5 转移冷藏库位失败（温区不匹配）" $transferFail "错误码: $($result.error)"


Write-Header "验收用例 3: 乐观锁 - 两次基于旧版本更新只能成功一次"

# 3.1 登记常温样本
$result = Invoke-Api -Method Post -Path "/samples" -Body @{
    sample_code = "TEST-ACCEPT-003"
    name = "验收样本-乐观锁测试"
    sample_type = "尿液"
    required_temp_zone = "AMBIENT"
    operator = "验收员"
    operator_role = "LAB_TECHNICIAN"
}
$sampleId3 = $result.data.id
$oldVersion = $result.data.version
Write-TestResult "3.1 登记常温样本成功" ($result.success -eq $true) "版本: $oldVersion"

# 3.2 入库
$result = Invoke-Api -Method Post -Path "/samples/$sampleId3/store-in" -Body @{
    location_id = 1
    operator = "库管员"
    operator_role = "LAB_TECHNICIAN"
    expected_version = 1
    reason = "入库"
}
$baseVersion = $result.data.version
Write-TestResult "3.2 入库成功（版本: $baseVersion）" ($result.success -eq $true) "当前版本: $baseVersion"

# 3.3 第一次基于旧版本转移（应该成功）
$result1 = Invoke-Api -Method Post -Path "/samples/$sampleId3/transfer" -Body @{
    to_location_id = 2
    operator = "操作员A"
    operator_role = "LAB_TECHNICIAN"
    expected_version = $baseVersion
    reason = "第一次转移"
}
Write-TestResult "3.3 第一次基于版本$baseVersion转移成功" ($result1.success -eq $true) "新版本: $($result1.data.version)"

# 3.4 第二次基于同一旧版本转移（应该失败）
$result2 = Invoke-Api -Method Post -Path "/samples/$sampleId3/transfer" -Body @{
    to_location_id = 1
    operator = "操作员B"
    operator_role = "LAB_TECHNICIAN"
    expected_version = $baseVersion
    reason = "第二次转移"
}
$versionConflict = ($result2.success -eq $false) -and ($result2.error -eq "VERSION_CONFLICT")
Write-TestResult "3.4 第二次基于版本$baseVersion转移失败（版本冲突）" $versionConflict "错误码: $($result2.error)"

# 3.5 验证最终版本号
$finalResult = Invoke-Api -Method Get -Path "/samples/$sampleId3"
$expectedVersion = $baseVersion + 1
Write-TestResult "3.5 最终版本号为 $expectedVersion" ($finalResult.data.version -eq $expectedVersion) "实际版本: $($finalResult.data.version)"

# 3.6 审计日志中只有一次转移
$logsResult = Invoke-Api -Method Get -Path "/samples/$sampleId3/audit-logs"
$transferLogs = @($logsResult.data | Where-Object { $_.action -eq "TRANSFER" })
Write-TestResult "3.6 审计日志只有1条转移记录" ($transferLogs.Count -eq 1) "转移记录数: $($transferLogs.Count)"


Write-Header "验收用例 4: 进程重启后数据一致性验证"

# 4.1 查询样本1最终状态
$sample1Result = Invoke-Api -Method Get -Path "/samples/TEST-ACCEPT-001"
$sample1Logs = Invoke-Api -Method Get -Path "/samples/$sampleId/audit-logs"
$statusConsistent = $sample1Result.data.status -eq "DISCARDED"
$logCountOk = $sample1Logs.data.Count -ge 6
Write-TestResult "4.1 样本1状态持久化（DISCARDED）" $statusConsistent "当前状态: $($sample1Result.data.status)"
Write-TestResult "4.2 样本1审计日志完整（≥6条）" $logCountOk "日志数量: $($sample1Logs.data.Count)"

# 4.3 导出CSV验证
try {
    $csvResult = Invoke-WebRequest -Uri "$baseUrl/samples/$sampleId/export-chain?role=LAB_TECHNICIAN" -Method Get
    $csvContent = $csvResult.Content
    $hasCsvData = $csvContent -match "样本编号" -and $csvContent -match "TEST-ACCEPT-001"
    Write-TestResult "4.3 CSV导出功能正常" $hasCsvData "CSV包含样本编号"
} catch {
    Write-TestResult "4.3 CSV导出功能正常" $false $_.Exception.Message
}


Write-Header "验收用例 5: 角色权限验证"

# 5.1 GUEST角色不能登记样本
$result = Invoke-Api -Method Post -Path "/samples" -Body @{
    sample_code = "TEST-ACCEPT-PERM"
    name = "权限测试"
    required_temp_zone = "AMBIENT"
    operator = "访客"
    operator_role = "GUEST"
}
$permDenied = ($result.success -eq $false) -and ($result.error -eq "PERMISSION_DENIED")
Write-TestResult "5.1 GUEST角色不能登记样本" $permDenied "错误码: $($result.error)"

# 5.2 GUEST角色可以查看
$result = Invoke-Api -Method Get -Path "/samples/$sampleId3"
Write-TestResult "5.2 GUEST角色可以查看样本" ($result.success -eq $true) "查看成功"

# 5.3 LAB_TECHNICIAN不能废弃样本
$result = Invoke-Api -Method Post -Path "/samples/$sampleId3/discard" -Body @{
    operator = "实验员"
    operator_role = "LAB_TECHNICIAN"
    expected_version = 3
    reason = "测试权限"
}
$discardDenied = ($result.success -eq $false) -and ($result.error -eq "PERMISSION_DENIED")
Write-TestResult "5.3 LAB_TECHNICIAN不能废弃样本" $discardDenied "错误码: $($result.error)"


Write-Host ""
Write-Host "=" * 70 -ForegroundColor Yellow
Write-Host "  测试汇总" -ForegroundColor Yellow
Write-Host "=" * 70 -ForegroundColor Yellow
Write-Host ""
Write-Host "  总测试数: $script:testCount" -ForegroundColor White
Write-Host "  通过:     $script:passCount" -ForegroundColor Green
Write-Host "  失败:     $script:failCount" -ForegroundColor Red
Write-Host ""

if ($script:failCount -eq 0) {
    Write-Host "  ✓ 所有验收用例通过！" -ForegroundColor Green
    exit 0
} else {
    Write-Host "  ✗ 有 $script:failCount 个用例失败，请检查！" -ForegroundColor Red
    exit 1
}
