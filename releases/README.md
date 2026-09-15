# releases —— 每個產品一個資料夾,合併器從這裡自動找最新版

## 命名規則

```
fpsup-<product>-v<major>.<minor>.<patch>[<qualifier>]
```

```
fpsup-gyro-v1.11b          機身端陀螺儀記錄器
fpsup-og3k-v0.2.3a         3:2 全片幅錄影(原生 UI、12-bit 全 ISO、8/10/12-bit alpha)
fpsup-og2k-v0.1.0test      3:2 全片幅錄影 2K(mode 139 quiet 讀出、八格率、8/10/12-bit)
fpsup-usbshell-v1.0.0      USB shell
```

`<product>` 是一個小寫詞,不帶版本、不帶日期。`<qualifier>` 可省略,
用來標「還不是正式版」:`test`、`a`/`b` 這類。

**同一個產品挑最新版的規則**:先比數字(`1.11` > `1.2`,逐段比整數,
不是字串),數字相同再比 qualifier —— 沒有 qualifier 的最新,
其次是字母(`b` > `a`),`test` 最舊。

## 每個資料夾裡

```
AutoRun.txt   必要
VSHL.BIN      必要
ABOUT.txt     必要(給網站用的一行說明,中英各一行)
README.txt    給使用者
MANIFEST.txt  可選,雜湊與建置紀錄
```

`AutoRun.txt` 與 `VSHL.BIN` 就是卡片的全部 —— 放進 SD 卡根目錄即可。

`ABOUT.txt` 是**首頁表格那一格的唯一來源**:

```
en: The same open gate at 2016×1344, on the sensor's quiet readout at every frame rate. 98 MB/s at 24p 12-bit, 8.3 ms rolling shutter. Test build.
zh: 同樣的 open gate,2016×1344,每個幀率都走感光元件的安靜讀出。24p 12-bit 為 98 MB/s,捲簾 8.3 ms。測試版。
```

一行就好,寫**這個產品是什麼**,不要寫這一版改了什麼 —— 版本專屬的測試紀錄屬於
`README.txt`。沒有 `ABOUT.txt` 時會退而取 `README.txt` 橫幅那一行。

## 版本從哪裡接下去

**接 `git tag`,不要接筆記。** USB shell 的上一個釋出是 tag `fp-usb-shell-v3.0.0`,
所以這次是 **v3.1.0** —— 自那之後 `fp_usb_shell/` 有 16 個 commit(echo 啟動、
熱抽換、載入器改從指令啟動),但 `shl` 的介面沒變,舊卡照樣能用,所以是 minor。

(筆記裡看得到 v27 那種編號,那是**已作廢的內部迭代** —— 走 EP 0x05 / EP 0x84,
而 EP 0x84 在現行描述元下不存在。別拿它接。)

## 加一個新版本

建好卡片,放進 `fpsup-<product>-v<版本>/`,附上 `ABOUT.txt`,然後:

```sh
tools/build_releases.py                  # 首頁與 README 的表格
tools/card-composer/build_catalogue.py   # 合併器的卡片目錄
```

**`index.html` 和 `README.md` 都不用手動改。** `build_releases.py` 掃 `releases/`,
每個產品挑最新的一版(用上面那條規則),把表格重新產生在
`<!-- releases:begin -->` / `<!-- releases:end -->` 之間。

來源是**資料夾不是 tag**:兩者依上面的規則是同一組,但資料夾才是網站真正連出去、
Pages 真正發佈的東西,而且在 workflow 的淺複製裡就有 —— tag 還要另外 fetch。

CI(`.github/workflows/pages.yml`)跑的是 `--check`:表格過期就讓部署失敗。
它**不會**自己改檔,因為 GitHub 的專案首頁是拿 commit 裡的 `README.md` 去算的,
不是拿 Pages 產物 —— 在 CI 裡改好也到不了那裡。

合併器同樣是**加版本不用改程式**(`latest()` 自己挑最新的資料夾);
只有**新增一個產品**才要在 `build_catalogue.py` 的 `PRODUCTS` 加一筆。
互斥也寫在那裡 —— 例如 OG2K 與 OG3K 各自 `excl` 指向對方,
因為解析度選單只有三格,兩者都要佔第三格。頁面會在勾選時自動取消另一個。

---

**fpSup** · [Ko-fi](https://ko-fi.com/fpsup) · [Discord](https://discord.gg/XeFK5zNZpT)
