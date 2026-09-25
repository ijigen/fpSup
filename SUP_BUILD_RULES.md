# sup 製作守則：AutoRun → loader → stage2 → entry

中文 · [English](SUP_BUILD_RULES.en.md)。兩份內容相同；改其中一份時，在同一個 commit 裡一起改另一份。
這份是規範；從頭解釋整個流程的說明在 [BUILDING.zh.md](BUILDING.zh.md)。

適用：SIGMA fp Ver.5.02，2026-09-23 整合後的載入流程。
讀者：製作新 sup、修改現有 sup 或維護合併建置的 agent。

這是製作規範，不是另一份開發日誌。實作證據與歷史數字見
[共用載入流程紀錄](../projects/usb-shell-sup/notes/CARD_BUILD_PIPELINE.md)，
OG 還原／錄影／QS 的證據見 [OG 共用穩定性紀錄](../projects/open-gate/notes/OG_BOOT_RESTORE_STABILITY_REVIEW_2026-09-23.md)。
兩份筆記位於完整研究專案中；只有 fpSup checkout 時可能不存在，應明說缺少哪些證據，不能自行補成「已驗證」。
現行程式與最新驗證若和舊註解不同，先釐清差異，不照抄歷史版本。

## 1. 先守住這五件事

1. **新增功能放 BIN，沿用共用載入器。** 不為每個 sup 複製一份 loader、stage2 或 AutoRun 產生器。
2. **entry 安裝完必須返回。** 常駐工作由自己的 worker／task 執行，不在載入入口裡永久迴圈。
3. **保留兩個 pass 與既有 entry ABI。** 不因某張卡沒用 pass 2 就刪掉；不加第三 pass 或自行解讀 entry 的回傳值。
4. **相容 payload 更新只換 BIN。** 不加 runtime BIN 雜湊、版本配對、pair ID 或其他要求每換 BIN 都換 AutoRun 的機制。
5. **只做本次需要的修改。** 不順便增加通用狀態機、跨 sup 失敗交易、全域配置框架或無關清理；真的需要改契約時先提出原因與相容性影響。

## 2. 使用同一條建置線

產品 builder 準備自己的內容，呼叫 [build_autorun.py](fp_usb_shell/build_autorun.py) 的 `--loader` 路徑，
產生 `AutoRun.txt` 與 `fpSup.BIN`；合併卡由既有 composer 使用同源的 AutoRun／stage2／Fast 模板封裝，
不另寫載入器。直接使用通用 builder 時，不含診斷 shell 的卡用 `--no-shell`。

- 固定位址的程式／資料區段：用既有 `--also`／`--also-bin`。
- 要在檔案載入位置執行初始化：用 `--boot-bin FILE:OFFSET`；適合自己配置記憶體並搬移常駐程式的 launcher。
- 已有固定位址初始化函式：用 `--vshl-entry ADDRESS`。
- **沒有 entry 就省略參數**，不要把 `--vshl-entry 0` 當作有效入口加入：0 是 header 的無入口值，也是多入口表的結束值。
- 封裝層必須保留上游的非零 entry，不能只重包區段卻丟掉入口；也不能假設所有純產品 entry 都是 0。
- 沿用 [entries.S](fp_usb_shell/templates/entries.S) 串接入口，不讓某個 sup 自己呼叫下一個 sup。
  通用 builder 的順序是 worker → 各 boot-bin（參數順序）→ vshl-entry；現行 OG＋gyro 即 worker → gyro → restore。
  新 sup 有初始化相依性時，在組裝處明確安排並驗證，不更動入口 ABI 或私下互相接力。

沿用產品的現行 builder：gyro 是 [build_base_card.py](gyro/build_base_card.py)；
OpenGate 是完整專案的 [build_og3k_gyro.py](../projects/open-gate/build/build_og3k_gyro.py)，
其 UI 來源是 [build_og3k_ui_candidate.py](../projects/open-gate/build/build_og3k_ui_candidate.py)。
不要退回歷史 builder、手工改生成的 BIN／AutoRun，或覆寫 frozen release 來讓比對通過。

普通產品卡與 Fast 最終封裝分開：現行 gyro／OG 出貨流程不直接帶 Fast；
合併出貨由 [card-composer](tools/card-composer/build_catalogue.py) 管理，開發合併卡沿用 `--dev-card`，
需要 Fast 才加 `--fast`。`--reference` 是比較基準，不冒充已上機或已發布的產品。

## 3. 載入順序不可偷換

1. AutoRun 放置並呼叫 loader；Fast 命中時由 store_boot 複製 loader、完成 D/I 快取處理後尾呼叫。
2. loader 配置自己的 staging buffer，開檔／讀檔／關檔，沿用現有 VBIN magic 檢查。
3. **loader 先 D-cache 維護，再 I-cache invalidate，才第一次執行 staging 裡的 stage2。**
4. stage2 放任何東西之前，先配置還原記錄（journal），並向 `XC_PowerOffMgr` 的兩張清單註冊 loader 的關機回呼。
   接著做 pass 1：放置固定位址區段——每個 cave 以外的韌體字，覆寫前先把原值記進 journal——然後 D/I publication。
   關機時回呼把 journal 寫回，相機以原廠狀態關機。
5. 呼叫 header entry；有多個入口就依序呼叫，**每個都必須返回**。
6. stage2 做 pass 2：放置 pool-offset 區段，然後再次 D/I publication。
7. 僅 Fast Start 2 封裝具有 store provision、abort 與 loader hook：
   只有確實有 AutoRun 在跑時才安排 abort；並把 `0xC03DA420`（啟動 AutoRun 的那條呼叫）指向 loader 的 `+4` 入口，
   讓暖開機不跑 AutoRun 就載入。stage2 返回，loader 釋放 staging。
   **Fast 命中且載入完成**時，下一個 echo 執行 abort，跳過慢路徑；
   首次／未命中的 fallback loader 返回後，AutoRun 還原 echo slot 並正常收尾，不再呼叫 abort。
   普通卡也照既有 AutoRun 收尾。

**兩種「小於 `0x40000000`」不是同一件事：**

| 欄位 | 0 | 非零且小於 `0x40000000` | 大於等於 `0x40000000` |
|---|---|---|---|
| section destination | 留在檔案中、不搬移（stage2／launcher 等） | pass 2 的 pool offset | pass 1 的絕對目的位址 |
| header／多入口表的 entry | header 表示無入口；表中表示結束 | 檔案 staging buffer 內的 offset | 絕對執行位址 |

位置與 offset 由 builder 重算。不要把某次建置的檔內 offset 寫死到另一個封包。
「entry 被呼叫」只表示走到該處，**不代表所有 sup 功能成功**；現有鏈不以 r0 判斷或中止後續入口。

## 4. entry、記憶體與快取責任

- entry 收到的 **r0 是它自己的已解析執行位址**，不是通用設定物件、pool pointer 或成功旗標。
  保留所用 callee-saved registers；有外部呼叫就保存 LR，並在每個呼叫點保持 SP 8-byte 對齊。
- 開機 entry 在 loader 的工作上下文執行，不等於後續 hook 也在同一種上下文。
  IRQ／類中斷回呼不可阻塞或任意做檔案 I/O；需常駐、等待或重工作時沿用已驗證的 task 方式。
- launcher 若要留下常駐程式／資料，先配置自己擁有的記憶體、複製及初始化，再安裝自己的 hooks。
  **不能讓 task、hook 或常駐資料繼續指向 staging**：loader 返回時會釋放它。
- 不假設上一個 sup 已配置好記憶體。`0xC3757A7C` 是既有 pool publication 字，
  不是 loader 的 staging 位址，也不是所有新 sup 都必須覆寫的公共變數。
  只有確實使用既有 pass 2 協定時，才依該協定管理 pool／offset／壽命；不要為新 sup 增加共享依賴。
- 大段常駐 body 優先放自己配置的區域；cave 僅放確實需要的短碼／指標。
  沿用現行配置機制並核對占用，不憑「讀到零」宣稱位址可用，不搬走其他 sup 或 USB 傳輸的工作區。
- 動態安裝自己的 hook 時，先準備好它會用到的程式、指標與資源，完成所需 publication，最後才 arm。
  配置失敗時不要讓該 hook 生效，保留可正常返回的路徑；這不等於替其他 sup 增加整包 rollback。
- **卡片改過的每個韌體字，由 loader 在關機時寫回，不由 sup 自己拆。**
  區段由 stage2 自動記錄。執行期才裝 hook 的 sup，要把每個 hook 位址宣告成一個 4 bytes 的區段、內容是韌體原字，
  讓 stage2 在 entry 之前把它記進 journal（參考：`build_base_card.py` 的 gyro `hook_sites()`）。
  sup 不再自己註冊關機回呼。hook 在「沒在錄影」時被觸發仍必須正確。
  原因與歷史見 [HOOKS_AT_POWER_OFF.md](HOOKS_AT_POWER_OFF.md)。
- 狀態字換位置時，**初值跟著搬**，並測試程式啟動時讀到的值，不只測位址。
- **撥電源開關是暖開機：映像與 cave 保留，BSS 清零，堆積重來。** 載入時不能假設要修補的位址還是原廠值
  （上一張卡或自己的舊版可能還在）；向韌體註冊的東西每次載入重做；指向池的東西不能留到下次開機（有宣告的位址由 loader 的關機寫回處理）。
  細節只寫在 [HOOKS_AT_POWER_OFF.md](HOOKS_AT_POWER_OFF.md)。
- 新寫入的 ARM 程式在首次執行前，沿用已驗證的 **`0xC000E91C()` → `0xC000EABC()`**。
  DSB、記憶體讀回正確、或「新程式進入後自己 flush」都不能取代首次執行前的快取處理。
- 已由 pass 1 寫入的靜態 hook 可能在 entry 前被原廠背景路徑碰到；它必須能安全處理尚未初始化的狀態。
  載入順序不是與 REC／QS 的互斥鎖，不能因此宣稱錄影中安裝也安全。

## 5. Fast start 與「只換 BIN」

合併頁面的選項是 **Fast Start 2**：這條設定區快路徑加上 loader hook，由同一次
`--store-boot --loader-hook --four-box-bar` 建置產生。暖開機時開機後約 1.4 秒就載入、不跑 AutoRun，
顯示四格畫面；冷開機時跑短版 Fast AutoRun。單一產品發布卡兩者都不帶。

Fast 只是縮短 AutoRun 拼出 loader 的工作，不是第二套 sup 初始化流程，**命中後仍重新讀 BIN**。
store_boot 命中 loader magic：複製 loader → D/I → 還原 LR 並尾呼叫；
未命中：返回，走同一張 AutoRun 的慢路徑。stage2 的 provision 寫 body 後才寫 magic。

magic 由 **loader bytes** 在 build 時推導；不是 BIN 版本，也不是開機時重算 stored body 的 hash。
不要讓產品名稱、內容長度、entry 或功能版本參與這個 magic。
bootstrap、loader、Fast stage2／abort 必須來自一致的封裝建置，不手動拼接新舊片段。
已帶 Fast 的成品不是一般 merge 輸入；由最終封裝一次加入 Fast，不讓各 sup 各帶一份。

- **只改相容 payload／entry，loader 與封裝配置不變：**允許只換 BIN；在主機端比對 AutoRun 不變。
- **真的改 loader bytes／ABI／檔名、Fast 開關或其封裝配置：**更新對應 AutoRun＋BIN 一次，說明原因。
  Fast 不能把新 BIN 的 provisioning 與舊 loader 混搭。
- **只有日期／產品版號改了：**不因此要求更換 AutoRun。不要把每次的 payload 版本或時間戳自動寫進 banner；
  若使用者明確要更新畫面名稱，AutoRun 改變是顯示需求，不是載入器要求綁版。

Fast 會使用具持久化能力的設定區，不能描述成「完全不寫任何持久化資料」。
這不授權修改其他設定欄位，也不授權 agent 自動把卡裝進相機。

## 6. 最小驗收與交接

在新的本機輸出目錄建置，不覆蓋卡片或凍結發行品。按修改範圍選測試，不要求每個小改動重跑無關產品。

- **每個 sup：**確認預期區段、entry 與組合順序沒有漏掉；使用既有 build-time 的大小、對齊、重疊檢查。
  沒有既有檢查覆蓋的新落點，要補對應的離線檢查，不拿掉守衛硬過。
- **支援合併／Fast：**驗自己的普通、debug、Fast 及有關組合；同 loader 配置改 payload 後，AutoRun 應不變。
- **動共用載入鏈：**在 `fpSup/fp_usb_shell` 跑 `python3 -B -m unittest test_boot_chain test_loader_hook test_splash`。
  `test_loader_hook` 用 unicorn 對著韌體映像執行真的 loader 與 stage2（hook 路徑、journal、關機寫回、三段式開機）；
  新測試第一次就過時，要故意改壞一行確認它會失敗（研究樹的技能 `fp-unicorn-emulation`）。
- **動 OG 入口、gyro pass-through 或 catalogue refs：**在完整專案根目錄跑
  `python3 -B projects/open-gate/build/test_boot_entry_chain.py`；預設使用新的暫存輸出目錄。
  保留 entry 0／guard-off 相容性；catalogue 驗證只呼叫 refs，不為了測試執行會改網站的 main。
- **會裝 hook 的 sup：**上機時做一次「開機、不錄影、關機，插卡再開」，重複約十次；
  錄影測試碰不到這條路（見 [HOOKS_AT_POWER_OFF.md](HOOKS_AT_POWER_OFF.md)）。
- **疊在上一張卡之上：**先用另一張卡（或自己的舊版）開機，撥電源開關，再用這張卡開機；
  確認它在「映像不是原廠狀態」時仍然正確。
- **新產品不在現有測試範圍內：**補該產品最小的 entry／安裝測試，不能拿 OG 測試通過代替它的驗收。
- **上機與發布另計：**建置、機器碼檢查、模擬、上機結果分開記。
  模擬器未成功執行就寫未驗證；未經明確授權，不寫卡、不操作相機、不 commit／push、不發布。

交接至少寫：修改範圍、建置命令與輸出位置、測試通過／失敗／未做、是否需要更新 AutoRun。
上機或交付的產物另記 SHA-256 以識別本次檔案，**僅供追溯，不變成 runtime 配對要求**。
日誌併入既有共用筆記並與相關 agent 協調；本守則只在製作契約確實改變時更新，不追加每輪實驗流水帳。

## 7. 查程式，不背過期數字

- [loader.S](fp_usb_shell/templates/loader.S)、[stage2.S](fp_usb_shell/templates/stage2.S)、
  [store_boot.S](fp_usb_shell/templates/store_boot.S)、[entries.S](fp_usb_shell/templates/entries.S)：執行契約。
- [build_autorun.py](fp_usb_shell/build_autorun.py)：容器、入口表、容量與封裝選項。
- [test_boot_chain.py](fp_usb_shell/test_boot_chain.py)：共用鏈回歸。
- [test_loader_hook.py](fp_usb_shell/test_loader_hook.py)：loader hook 與關機寫回的模擬執行。
- [releases/README.md](releases/README.md)：真正獲准發布時的命名與打包規則；版號查目前 tags／產物，不抄舊例子。

loader 大小、AutoRun 條數與速度屬於具體建置的結果，不在新產品中複製另一份硬編碼常數。
