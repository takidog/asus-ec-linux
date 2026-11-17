# ASUS EC Linux 風扇監測與控制

[English](README.md) | **繁體中文**

透過 ASUS 特定嵌入式控制器（EC）的已驗證介面，在 Linux 讀取風扇轉速及切換韌體風扇模式。目前研究對象為 ASUS 的 ITE IT8225 韌體介面，**實機測試平台是 VivoMini VC66-C2、BIOS 1602**。其他主機即使用相同 EC，也需要獨立驗證暫存器配置。

實測切換全速後，CPU 風扇由 **3,237 RPM 升至約 5,300 RPM**；恢復 Normal 並等待穩定後為 **3,267 RPM**。過程沒有重新開機，也沒有修改 BIOS 儲存的設定。

後續溫度對照測試中，在既有 VM 工作負載下，全速階段末段的 CPU 封裝平均溫度約降低 **7°C**。詳見[量測時段、功耗與曲線](docs/vc66-c2.md#cpu-temperature-comparison)。

## 功能

- 讀取 CPU 風扇 RPM 與目前 EC 模式。
- 切換 **Normal** 或 **全速**（關閉 BIOS QFan 調速）。
- 暫時切換全速，測試結束後自動恢復原模式。
- 選用的 [Proxmox VE 整合](docs/pve.md)，顯示溫度、風扇 RPM，並提供 Normal／全速切換。

目前屬於實驗性硬體支援。Quiet 模式已在韌體中辨識，但尚未實測，因此未提供設定指令。目前也沒有任意 PWM 百分比或自訂溫度曲線功能。

## 使用方式

需要 Linux、Python 3.9 以上、root 權限、核心 `ec_sys` 模組，以及已掛載的 debugfs；載入模組後應有 `/sys/kernel/debug/ec/ec0/io`。請在實體主機執行。

```sh
git clone https://github.com/takidog/asus-ec-linux.git
cd asus-ec-linux

# 讀取轉速與模式，不寫入 EC 暫存器。
sudo python3 tools/asus_ec.py status

# 全速測試 10 秒，再恢復原模式。
sudo python3 tools/asus_ec.py test-full-speed --seconds 10

# 選擇模式，直到韌體再次修改或主機重新啟動。
sudo python3 tools/asus_ec.py set-mode full-speed
sudo python3 tools/asus_ec.py set-mode normal
```

輸出為逐行 JSON，包含 profile、模式、原始模式值與 RPM。設定僅作用於當下 EC 狀態，不寫入 BIOS 變數、不安裝常駐服務，也不會在重新開機或喚醒後自動套用。切換模式後，實際轉速需要時間才會穩定。

## 相容性與限制

| 平台 | RPM | Normal／全速 | Quiet |
| --- | --- | --- | --- |
| VC66-C2、BIOS 1602 | 已實測 | 已實測 | 僅確認韌體定義 |
| VC66-C2、BIOS 1603 | 未實測；相關 EC／感測器／WMI 模組與 1602 相同 | 未開放 | 未實測 |
| 其他使用 ITE IT8225 的 ASUS 主機 | 暫存器配置未驗證 | 未開放 | 未實測 |

程式以 DMI 廠商、主機板與 BIOS 版本選擇 profile，拒絕未知組合，沒有強制套用或任意寫入暫存器選項。專案可以加入其他已驗證的 ASUS 主機，不限於第一台測試平台。

程式只操作已確認的模式位元組，要求 EC bank 為零，且不會切換 bank。寫入前的模式必須是已驗證可恢復的 Normal 或全速。寫入後會回讀確認，並以獨立 watchdog 處理操作失敗、父程序中斷或逾時時的還原；成功的 `set-mode` 會保留指定模式。

若 `ec_sys` 已載入，查詢會保留既有狀態，控制指令則拒絕變更它的設定。由工具載入的模組，會於操作結束後關閉寫入並卸載。暫時測試限 1–30 秒。程序鎖只能協調本工具，無法鎖住韌體或其他 EC 工具，請避免同時操作；核心或韌體失效時無法保證還原，多次 EC 交易也不是原子操作。

## 研究與 PVE

可用的調速路徑來自 Ghidra 對 ASUS BIOS 風扇設定 callback 與感測器模組的分析，再以 Linux 上的實際 RPM 變化驗證。它透過 `ec_sys` 使用核心的 ACPI EC 存取，不需要自製直接操作 I/O port 的驅動。

檢查過的韌體雖然宣告 ASUSManagement WMI 風扇方法，但 getter 回傳空資料，setter 回報不支援。Windows 的 WMI／COM 包裝函式不能讓這些未實作的方法自動變得可用。[VC66-C2 研究紀錄](docs/vc66-c2.md) 列出暫存器、韌體識別、Windows 呼叫路徑與其他主機的 EC 證據。

`tools/probe_fan_policy.py` 僅診斷 WMI 路徑；其中 `control_supported: false` 不代表獨立 EC 路徑無法控制。

[PVE 擴充](docs/pve.md) 透過 hwmon 顯示溫度；安裝時加上 `--fan-control`，即可在 **Node → Summary** 顯示 EC 風扇 RPM 與 Normal／全速切換。EC 讀取由獨立背景程序執行，節點狀態 API 只讀取有大小限制的快取。調速使用非同步 PVE 工作，要求節點的 `Sys.Modify` 權限；PVEAdmin 角色本身沒有這項權限。已測試 PVE 8.4.19／Linux 6.8.12-30-pve。

## 開發

以下測試使用模擬資料，不會存取實際硬體：

```sh
python3 -m unittest discover -s tests -v
perl tests/test_thermal.pl
```

詳見[測試說明](docs/testing.md)。新增其他主機支援時，請提供主機板／BIOS／核心版本、暫存器配置的證據、去識別化的 RPM 與模式測試，以及可驗證的還原方式。請勿提交憑證、序號、主機位址、完整韌體或 ASUS 專有程式。

原創程式與文件採 MIT 授權。專有軟體及下載的 PVE 測試資產不隨專案散布，仍適用各自授權。
