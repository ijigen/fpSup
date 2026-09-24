# fpSup 卡片怎麼運作、怎麼做一張

[English](BUILDING.md) · 中文

這是完整的流程說明:卡片裡有什麼、相機開機時發生什麼事、怎麼寫自己的功能(一個「sup」)、
怎麼跟別的 sup 合併、怎麼測試、怎麼發布。建議從頭讀到尾。

精簡、嚴格的版本是 [SUP_BUILD_RULES.md](SUP_BUILD_RULES.md) —— 那份是規範,這份是解說。
兩者有出入時以規範為準,並修正這一份。

只適用 SIGMA fp 韌體 Ver.5.02。文中所有位址都只對這個韌體有意義。

---

## 1. 一段話講完

fp 開機時,如果 SD 卡上有 `AutoRun.txt`,韌體會執行這個腳本。腳本可以往記憶體寫字。
我們用它寫進一個小小的 **loader**;loader 再去讀第二個檔 `fpSup.BIN`,裡面裝著其他
所有東西:程式、資料、對韌體的補丁。**什麼都不寫進相機的 flash**(唯一例外是可選的
Fast start,見第 7 節)。關機、拔卡,相機就是原廠狀態。

一個 **sup** 就是用這種方式包起來的一個功能:陀螺儀記錄、open gate、USB shell。
多個 sup 可以放在同一張卡上。

## 2. 卡片上有什麼

```
SD 卡根目錄
├── AutoRun.txt    文字腳本,補齊到固定長度(約 32 KB)
└── fpSup.BIN      裝著多個「區段」的容器,補齊到 32 KiB 以上
```

**AutoRun.txt** 會畫進度條、用 `mem set` 一個字一個字把 loader 寫進記憶體、借用韌體的
`echo` 指令去執行它,最後畫出 banner —— 例如 `fpSup-Gyro-v1.13.1!`。
**banner 是分辨相機裡裝的是哪張卡的唯一方法。**

**fpSup.BIN** 開頭是一個小表頭,接著是區段表,最後是各區段的內容:

```
"VBIN" | 區段數 | entry | 內容長度
(目的地, 長度) × 區段數
各區段的位元組,每段補齊到 4 的倍數
```

每個區段的**目的地**決定它放到哪裡:

| 目的地 | 意思 |
|---|---|
| 0 | 留在檔案載入的位置,就地執行(輔助程式、launcher) |
| 小於 `0x40000000` | 相對於 payload 開機時要到的那塊記憶體(「池」)的偏移 |
| `0x40000000` 以上 | 相機記憶體的絕對位址(韌體補丁、cave 裡的程式) |

**entry** 是區段都放好之後要呼叫的位置,0 表示沒有。

## 3. 相機開機時發生什麼

```
開機
  │
  ├─ 韌體照常啟動,找到 AutoRun.txt,開始執行
  │
  ├─ AutoRun:畫進度條,再用約 70 條 `mem set` 把 LOADER 寫進
  │           韌體記憶體裡一小塊沒用到的空間(「cave」)
  │
  ├─ AutoRun:把 `echo` 指令指向 loader,然後執行 `echo`
  │    │
  │    └─ LOADER:向配置器要一塊暫存緩衝區,把 fpSup.BIN 讀進來,
  │               檢查 "VBIN",清快取,跳進第一個區段:
  │         │
  │         └─ STAGE2(放在 BIN 裡、跟著卡走的輔助程式):
  │              第一輪  放好所有絕對位址的區段
  │              ─────── 清快取
  │              呼叫 entry —— 每個 sup 的安裝程式,一個接一個;
  │              每個都必須返回
  │              第二輪  放好所有池偏移的區段
  │              ─────── 清快取,返回
  │
  │         loader 釋放暫存緩衝區,返回
  │
  └─ AutoRun:把 `echo` 還原,畫出 banner。完成。
```

這裡要記住兩件事:

- **你的程式只在開機時、在 loader 裡面跑一次,而且必須返回。** 之後還要持續運作的東西,
  要嘛是韌體會跳進來的補丁(hook),要嘛是你自己建立的 task。
- **新程式執行前一定要清快取。** ARM 核心的資料和指令是兩個分開的快取,剛寫進去的位元組
  還不會被當成指令看到。loader 和 stage2 放的東西都會替你處理;如果你的程式在執行期間
  自己寫程式碼,執行前要先呼叫 `0xC000E91C()` 再呼叫 `0xC000EABC()`。

## 4. 東西放在記憶體的哪裡

| 區域 | 是什麼 | 關機後還在嗎 |
|---|---|---|
| 韌體映像 `0xC0000000…` | 韌體自己的程式和資料,補丁寫在這裡 | **不在** —— 每次開機從 NAND 重新載入,所有補丁都會消失 |
| **cave** `0xC072DE64…0xC0730000` | 韌體映像裡幾 KB 沒用到的空間,放 loader 和必須在固定位址的小東西 | 不在,同上 |
| 配置器給的記憶體(**池**) | 開機時要來的記憶體,放大段程式和緩衝區 | 內容可能殘留幾分鐘,但配置器會交給別人用,當作不在 |
| 設定區 `XC_CommonSaveData` | 相機自己存設定的地方 | **在**,拔電池也在。只有 Fast start 會寫這裡 |

cave 很小又是大家共用,所以有個簡單的配置器:`0xC072E060` 這個字記著下一個空位,
stage2 每次開機重設它,sup 要多少就往上加多少。**不要自己挑 cave 位址。**

## 5. sup 改變相機的兩種方式

**靜態補丁。** 目的地是絕對位址的區段,在載入時直接蓋掉韌體的字。open gate 就是這樣:
幾百個字的表格和分支,全部在其他東西執行之前由 stage2 放好。簡單,而且它們跳去的程式
也在韌體記憶體(cave)裡,直到關機都有效。

**執行期 hook。** 你的 entry 要一塊記憶體、把程式複製進去,再把韌體的某一條指令換成
跳到那段程式的分支。陀螺儀記錄就是這樣,因為它的程式太大,cave 放不下。這種方式比較
靈活,但有一條很容易漏掉的規則:

> **hook 的程式如果不在韌體映像裡,關機時就必須拆掉。** 裝任何 hook 之前先註冊關機
> 回呼,註冊失敗就一個都不裝。

留著不拆的 hook 會在關機途中被觸發,跳進正在被拆掉的記憶體。gyro v1.13 就是因此讓
相機在下次開機時凍結。完整經過、韌體的回呼介面和參考實作,在
[HOOKS_AT_POWER_OFF.md](HOOKS_AT_POWER_OFF.md)。

## 6. 寫一個 sup、建成卡

### 需要什麼

- Python 3
- 能輸出 `armv7-none-eabi` 的 `clang` —— 近期的 clang 都可以,不需要交叉編譯工具鏈
- 要核對位址的話,韌體映像 `out/MAIN_c0000000.bin`
- 測試用:一台 Ver.5.02 的 SIGMA fp 和一張 SD 卡

### 寫程式

sup 用 ARM 組合語言(`.S`)寫,由 `fp_usb_shell/armasm.py` 呼叫 clang 組譯。相機沒有
動態連結器:程式碼是原封不動複製過去的,所以必須在放置的位址上能跑(開機時才複製的話,
就要寫成跟位址無關)。

**entry**(stage2 呼叫的安裝程式):

- `r0` 是 entry 自己的位址。保存你用到的 callee-saved 暫存器;有呼叫別的函式就保存
  `lr`;每次呼叫時 `sp` 都要 8 位元組對齊 —— 否則韌體的 `LDRD` 會出錯。
- 做完事就**返回**,不要在這裡無限迴圈。
- 自己向配置器要記憶體,不要假設別的 sup 已經要過。
- 要裝 hook:先準備好它的程式和資料,再註冊關機回呼,**最後**才寫入分支。
- 配置失敗就什麼都不裝、正常返回。只成功一半的卡,比什麼都不做的卡更糟。

**hook**(之後韌體會跳進來的程式):

- 隨時可能被觸發,而且是在韌體當下所在的 task 裡,可能是類似中斷的情境。不要阻塞,
  也不要在這裡讀寫檔案;重的工作交給 task。
- 沒在錄影時被觸發也要正確;如果是靜態放的,在你的 entry 跑之前被觸發也要正確。
- 狀態從一個地方搬到另一個地方時,**初值要跟著搬**。「0xFFFFFFFF 代表還沒開始」
  這種值很容易搬丟。

### 建卡

全部都走同一個工具 `fp_usb_shell/build_autorun.py --loader`,它會一起產生 `AutoRun.txt`
和 `fpSup.BIN`。常用選項:

| 選項 | 用途 |
|---|---|
| `--also ADDR:SRC` | 組譯 `SRC`,放到固定位址 |
| `--also-bin ADDR:FILE` | 把原始位元組放到固定位址(小於 `0x40000000` 則是池偏移) |
| `--boot-bin FILE:OFFSET` | 在檔案載入位置執行的 launcher:要記憶體、複製自己、安裝 |
| `--vshl-entry ADDRESS` | 已經放在固定位址的安裝程式 |
| `--no-shell` | 不帶 USB shell —— 每張產品卡都用這個 |
| `--banner TEXT` | 載入完成時顯示的文字,最多 19 個字元 |
| `--out DIR` | 兩個檔案輸出到哪裡 |

現有產品都有自己的 builder,會用正確的參數呼叫它。請用它們,不要手動呼叫:

```sh
# gyro(Gyroflow 記錄器)
python3 gyro/build_base_card.py --edition gcsv --version dev --out /tmp/gyro-card
# 同上但帶 USB shell,用來在相機上除錯
python3 gyro/build_base_card.py --edition gcsv --debug --version dev --out /tmp/gyro-dbg
```

open gate 的 builder 在完整研究專案裡(`projects/open-gate/build/build_og3k_gyro.py`),
不在這個 repository。

每個 builder 在寫檔之前都會檢查:區段不能重疊、不能超過 loader 讀得到的範圍、
不能落在 loader 正在使用的地方。檢查失敗就修正原因,**不要拿掉檢查**。

## 7. 合併多個 sup,以及 Fast start

**fpSup-Merge** 在瀏覽器裡把已發布的 sup 合併成一張卡:
<https://ijigen.github.io/fpSup/tools/card-composer/>。勾選要的卡,就能下載
`AutoRun.txt` 和 `fpSup.BIN`。也可以把你自己的 `fpSup.BIN` 拖進去一起合併。

合併時它會做這些事:

- 保留每張卡的所有區段,完全相同的只留一份
- 丟掉每張卡自己的 stage2,換成**一份**目前的版本
- 依固定順序串接 entry(USB shell → gyro → open gate 的還原)
- 用自己的模板產生 AutoRun,所以它做出的每張卡都用目前的 loader
- 檢查結果,任何一項失敗就停用下載按鈕 —— 包括拒絕「上傳的卡需要比頁面更新的 stage2」

**Fast start** 是頁面上的一個開關,能省掉大約一半的開機腳本:第一次開機時 loader
把自己複製進相機的設定區;之後每次開機,腳本檢查一個指紋,對得上就直接執行存著的
loader,不用再一條條寫出來。指紋對不上(換了卡、loader 更新了)就照常走慢路徑,
順便存入新的。

Fast start 是**唯一**會寫進持久記憶體的東西。它撐得過拔電池,刪掉 `AutoRun.txt`
也還在,所以要由安裝的人自己選擇;單一產品的發布版一律不帶。從選單重置相機設定
**應該**會清掉它,但沒有實測過。

## 8. 在相機上測試

1. **不要插 USB 線**,插卡開機。
2. 看進度條,它會從 `fpSup[........]000` 一路跑到 banner。
   **進度條停在哪裡,載入就停在哪裡**,位置大致告訴你是哪一段出錯。
3. 確認 banner 是你要測的那一版。
4. 照這個 sup 的用途操作:錄影、開選單、切換模式。
5. 會裝 hook 的 sup 還要測:開機、**不錄影**、關機,再**插著卡**開機。重複約十次。
   錄影測試碰不到這條路。
6. Fast 卡:開兩次機。第一次慢、會存 loader;第二次 banner 只畫一次、進度條大部分跳過。

`--debug` 版帶 USB shell,出問題後可以透過 USB 讀記憶體(見 `fp_usb_shell/README.md`)。
發布版一律不帶。

相機凍結了:拔電池、拔卡、再開機,就是原廠狀態。測試前先記下卡片檔案的 SHA-256,
這樣測試結果才能對應到確切的位元組,而不是一行指令。

## 9. 發布

一個發布版就是 `releases/` 底下的一個資料夾:

```
releases/fpsup-<產品>-v<版本>/
├── AutoRun.txt
├── fpSup.BIN
├── ABOUT.txt     英文、中文各一行,給網站表格用
└── README.txt    給安裝的人看
```

它的位元組是凍結的:發布版永遠不重建、不就地修改。步驟:

1. 用產品的發布腳本建卡 —— gyro 是 `gyro/release_card.py gcsv v1.13.1`,它會重建、
   檢查每個區段都在,並產生 zip 和校驗碼。
2. 放進 `releases/fpsup-<產品>-v<版本>/`,附上 `ABOUT.txt`。
3. `python3 tools/build_releases.py` —— 重新產生網站和 `README.md` 裡的表格。
   表格過期的話,GitHub Pages 的部署會失敗。
4. `python3 tools/card-composer/build_catalogue.py` —— 重新產生 fpSup-Merge。
   任何組合重現不出來,它就拒絕寫出頁面。
5. 用資料夾名稱打 tag:`git tag -a fpsup-<產品>-v<版本>`。
6. 推送 `main` 和 tag,GitHub Pages 會部署網站和合併頁。
7. fpSup-Merge 的 Claude Artifact 版是分開的,要另外手動發布
   `tools/card-composer/artifact.html`。

版號接著 tag(`git tag`)往下編,不要接筆記裡的編號。

**撤回**一個發布版:把資料夾搬到 `history/withdrawn-<日期>/`,附一份 README 說明原因,
刪掉它的 tag,重新產生表格和合併頁。修正版出來後,在那份 README 寫明是誰取代了它。

## 10. 名詞

| 名詞 | 意思 |
|---|---|
| sup | 從卡片載入的一個功能(gyro、open gate、USB shell) |
| AutoRun | 韌體從卡片執行的開機腳本 |
| loader | AutoRun 寫進去的小程式,負責讀 `fpSup.BIN` |
| stage2 | `fpSup.BIN` 裡的輔助程式,負責放區段、呼叫 entry |
| 區段 | BIN 裡的一塊內容,帶著目的地 |
| entry | sup 的安裝程式,stage2 呼叫一次 |
| cave | 韌體記憶體裡一小塊沒用到的空間,透過配置器共用 |
| 池 | sup 開機時向相機配置器要來的記憶體 |
| hook | 被換成「跳進 sup 程式」的一條韌體指令 |
| Fast start | 把 loader 存進設定區,讓之後的開機更短 |
| banner | 載入完成時顯示的文字,用來辨認是哪一版 |
