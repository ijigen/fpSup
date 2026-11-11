# fpSup-Merge v4

Loader v4 的合併頁(2026-10-24 使用者指示另開；`tools/merge-v3/` 與網站入口不動)。

```text
python3 -B tools/merge-v4/build_inputs_v4.py --out tools/merge-v4/inputs/v4-YYYYMMDD   # 新快照(不覆蓋舊的)
python3 -B tools/merge-v4/build_catalogue_v4.py                                       # 寫 index.html
node tools/merge-v4/test_merge_v4.js
node tools/merge-v4/test_ui_v4.js
node tools/merge-v4/test_upload_v4.js
node tools/merge-v4/test_lazy_v4.js
python3 -B -m unittest discover -s tools/merge-v4 -p "test_*.py"
python3 -B tools/merge-v4/publish_releases.py            # 每個提供中的版本在 GitHub 上是不是 Release(只讀)
```

**2026-11-11 鏡像站自己計數**(Bei 定：`fpsup.ijigen.xyz` 是給連不到 GitHub 的人用的，下載次數另外算):
- 頁面在鏡像網域(`CAT.mirror.host`)上按「下載 zip」時，對同網域 `POST /count/<tag>/<檔名>`(每檔每次造訪一次),
  **不碰 GitHub**;在 GitHub Pages 上照舊請求 Release asset。兩邊不重複，合計 = GitHub + 鏡像。
- 下載數兩個網域都先讀鏡像站的 `/counts.json` = `{updated, since, github:{tag/檔名:n}, mirror:{tag/檔名:n}}`
  (GitHub 的數字由鏡像站代抓，所以連不到 GitHub 也看得到);讀不到才退回 GitHub API(那時沒有鏡像的數字)。
  磚上的數字是合計，滑過去多一句「其中鏡像站 N 次」。
- 鏡像站那一側**不在 repo 裡**,在 CT124:nginx `conf.d/fpsup-count.conf` + site 的 `/count/`(只記一行、回 204、
  每來源 2 次/秒)與 `/counts.json`;`/usr/local/bin/fpsup-counts.py` 由 `fpsup-counts.timer` 每 5 分鐘彙總：
  只認部署頁面裡現有的 tag/檔名、只認 POST、同一來源同一檔一小時算一次(來源只以加鹽雜湊暫存);
  累計值在 `/var/lib/fpsup-counts/state.json`(刪掉就歸零),2026-11-11 起算。
- 測試：`test_lazy_v4.js` 第 6、7 段(兩個網域讀 counts.json、鏡像上只發 POST 不連 GitHub)。

**2026-11-10 下載量：每個版本一個 GitHub Release、頁面不內嵌 sup**(Bei 定):
- **頁面不再帶 sup 的位元組**(index.html 2.26 MB → 0.91 MB;剩下的是四組開機檔與 splash)。目錄裡每個 sup／資料檔只有
  `size`、`sha256`、`src`(網站上的位置 = `inputs/<快照>/<檔>`,本來就隨 Pages 發布)、`asset`(Release 資產網址)。
  勾選時才抓 `src`,大小與 sha256 跟目錄相同才收下(`accept`),不同就顯示原因與「重試」;抓完才跑原本的自檢、才能下載。
  同一個選擇產生的 zip 與內嵌版逐位元組相同(54 組選擇 × 開機組合比對過)。
- **為什麼不是直接從 Release 抓**:Release 資產最後由 `release-assets.githubusercontent.com` 回應，沒有 CORS 標頭(2026-11-10 實測),
  瀏覽器的 JS 讀不到內容。所以位元組走同網域的 `src`,**計數**另外做：按「下載 zip」時對卡上每個檔的 `asset` 發一次
  `fetch(..., {mode:'no-cors'})`(`countDownloads`)。每次造訪每個資產只算一次；本機開啟(file://、localhost)不算。
  **實測會算**(2026-11-10,拿 `ijigen/gyroflow-plugins` 的舊 Release 資產、headless Chrome、來源 `ijigen.github.io`):
  1 次 no-cors → +1;連續 3 次 → 只 +1(GitHub 會合併同一來源短時間內的重複);數字 10~15 分鐘後才反映在 API。
- **顯示**:頁面載入時問 `api.github.com/repos/ijigen/fpSup/releases`(有 CORS、免登入、每 IP 每小時 60 次),圖磚版本旁顯示
  「↓ 下載 N 次」= 該 sup 所有版本(tag `fpsup-<id>-v*`)的 .BIN 下載數合計，滑過去看目前版本的數字。問不到就不顯示。
- **Release 的樣子**:tag = 快照 manifest 的 `release`(`fpsup-lossless-v0.3.1`),資產 = 該 sup 的 .BIN 與資料檔
  (RES-Custom 的五個 .RCD 是它那個 Release 的資產，各有各的計數)。版本帶 `test` 的標 prerelease。
- **`publish_releases.py`**:讀 index.html 的目錄(頁面實際用的那份)。無參數 = 列出缺什麼；`--check` 缺就 exit 1;
  `--publish`(要 `GH_TOKEN`)先建 draft、傳完資產才公開。**已存在的 Release 永不改寫**:同名資產位元組不同就整個停下 ——
  改了位元組就是新版本(`names_v4.py` 進版 → 新 tag、新計數)。中斷後重跑會接著做完。
- **發布順序**:Pages workflow 在部署前跑 `--publish`,所以推上去的頁面不會指到不存在的資產。workflow(合併 repo 根目錄
  `.github/workflows/pages.yml`)要加(同步到 worktree 時一起改):
  ```yaml
  permissions:
    contents: write        # 原本是 read;建 Release 需要
  # ...「Releases tables are current」之後、upload-pages-artifact 之前:
      - name: Offered sups are GitHub Releases
        working-directory: fpSup
        env:
          GH_TOKEN: ${{ github.token }}
        run: python3 tools/merge-v4/publish_releases.py --publish --target "$GITHUB_SHA"
  ```
- `tools/card-composer/index.html` 是這頁的複本：`src` 先試自己資料夾、404 就改用 `../merge-v4/`(`src_bases`),之後都先問有效的那個。
  所以複本不用另外建，但 `inputs/` 用到的快照要一起 commit。
- 測試:`test_lazy_v4.js`(假 fetch 供檔：不勾不抓、只抓勾的、sha 不對不收、斷線、複本路徑、計數一次且 no-cors、本機不計數、
  API 數字只加該 sup 的 .BIN;11 個突變全抓到)、`test_publish_releases.py`(假 GitHub;7 個突變全抓到)、
  `test_fill.js`(舊測試改從磁碟依 `src` 填位元組)。headless Chrome 實開過：勾 RES-Custom 抓 6 個檔、再勾 Lossless 抓 2 個。

**2026-11-10 Lossless 0.3.2test、Sensor Lab 0.0.6test、QS-Share 0.0.2test**(Bei 經 SensorLab 那條線：更新 merge 頁):
- 新快照 `inputs/v4-20261110c/`(`build_inputs_v4.py --only sensor-lab,qs-share,lossless`;`v4-20261110` 已被 Dial Fix 用掉；
  `b` 是帶 Sensor Lab 0.0.5test 的那份，當天被 0.0.6test 取代、從未發布，已刪)。
  三個檔與 SensorLab 那條線上機驗證的檔 sha256 相同(a174779d…、36f24a12…、4939f399…);上機範圍寫在快照 `manifest.json` 的 `validation`
  (build_inputs 自動填的那句是 0.0.1test 時代的，已手動換掉；`VALIDATION_OF` 下次要一起更新)。
- `build_catalogue_v4.py`:同一個產品出現在兩份快照時，**`INPUTS` 排後面的取代前面的**(建頁時印出「replaces」);同一份快照內重複、
  或後面的快照重複同一個 release tag 仍然中止。被取代的版本記在產品的 `superseded`,`release_history.py` 把它排進版本歷史(非 current、帶 `version_notes.json` 的說明)。舊版(Lossless 0.3.1、Sensor Lab／QS-Share 0.0.1test)的 Release 留在 GitHub,計數各算各的。
- Bei 當天看過本機頁後(經 sigmafp-re-18):Sensor Lab 0.0.6test 說明改成只講這版做什麼(不和舊版比);RES-Lab 不再有圖磚
  (拿掉 `pending`);LUT 圖磚顯示「Coming Soon／即將推出」、不可選(新 stage `coming`,留在自己的分類)。Sensor Lab 圖磚的更新提醒不再寫死 0.0.1test。
- push 時 workflow 新建三個 Release(都是 prerelease)。這次只推頁面、快照與 `names_v4.py` 三行;Lossless／Sensor Lab／QS-Share 的原始碼
  由各自那條線另外同步進 repo(快照 `manifest.json` 的 `source_sha256` 記的是建檔當時的本機原始碼)。

**2026-11-12 LUT 0.1.0test + COL-Share 0.0.1test + RAW-View 0.4.0test**(Bei 定;本機，未 commit、未發布):
- 快照 `inputs/v4-20261112/`(`build_inputs_v4.py --only lut,col-share,raw-view`)。LUT 的 builder 是 `fpSup/lut/build_v4_lut.py`
  (空的清單；`UI/COLOR.BIN` 是 support file,一定跟著);COL-Share 是 `infra`(像 QS-Share,LUT 與 RAW-View 都 `requires` 它)。
- RAW-View 換成 0.4.0test(COL-Share 的客戶，`build_v4_rawview.py --cols`);names_v4 進版也讓 COL-Share 的 RAW-View 探測檔名跟著變。
- LUT 的資料檔是 `fpSup/LUT/*.cube`(`fpSup/lut/looks/make_looks.py`)。**目前一支都不附**(Bei 2026-11-12):
  LogC3、L-Log 的校準一步是 Luka/Midnite 的 v0.3(驗證對照 Ole Berek),拿到兩位同意前隱藏 ——
  `make_looks.LOOKS` 註解掉、目錄 credits 清空、`guide/lut.html` 第 6 節包在註解裡;Spectral Film LUT 也不放,
  `data.optional`:一支都不勾也是有效的卡(用戶自己放 .cube 就能用)。資料檔與 support file 的卡上路徑 = `fpSup/` + 快照裡的相對路徑。
- 驗證：這組位元組還沒上機(manifest 的 validation 寫 PENDING)。

和 v3 頁的差別：
- **產品全部來自一份快照** `inputs/v4-20261025/`(2026-10-25:選單掉鍵修正、頁尾固定、sup 檔名帶版本):`build_inputs_v4.py` 跑各產品自己的 v4 builder
  (`loader-v4/ports.py`、`ports_jose.py`、`lossless/build_v4_lossless.py`、`screenflip/build_v4_flip.py`、
  `projects/rawview/build/build_v4_rawview.py`、`projects/open-gate/build/res-custom-v4/build_v4_rescustom.py`),
  manifest 記每個檔的 size/sha256 與 builder 原始碼雜湊。v3 的 release 只當版本紀錄，不讀產品。
- **fpSup 頁一律附上**(使用者：關掉的話 Lossless 開關、Res-Custom 檔案頁就沒地方用):
  每張卡都有 `fpSup/SUPMGR.BIN`、`fpSup/UI/FPSUP.BIN`、`fpSup/UI/SUPMGR.BIN`;勾選框顯示為已勾、不可取消。沒有 v3 的 `ALLSUPS.BIN`。
- **開機檔**:`loader-v4/build_v4.py` 的 `boot_card(splash, instant, fast, slim, ui)`,四組(瞬間啟動 × 快速啟動)。
  預設瞬間啟動開、快速啟動關。LOADER.BIN 尾端是空的停用清單(FSDS)。
- 檔名沒有 v3 的數字前綴(DSQZ、FCAP、FLIP、GYR2、LOSS、RAWV、RESCUS、SHELL、STOPFX、TAPZ、ULWR),載入順序 = 檔名順序；
  頁面自檢改成 FSB4 檔頭(48 B)。Loader v4 不載入 v3 sup,README 提醒先刪卡上整個舊 `fpSup`。

**2026-11-07 Sensor Lab-IMX410 + QS-Share**(Bei 定;本機頁面，未 commit、未發布):
- 新快照 `inputs/v4-20261107/` 只放這兩個(`build_inputs_v4.py --only sensor-lab,qs-share`,跑 `projects/sensorlab-imx410/qs/build_slqs.py`
  與 `projects/qs-container/build_qsct.py`);其他產品仍讀 `v4-20261027/`(`INPUTS` 兩份)。名稱/版本在 `loader-v4/names_v4.py`(SL41、QSCT)。
- `infra`(QS-Share):共用元件，不是選項 —— 沒有圖磚、不被「全選」選到;Sensor Lab `requires` 它，所以勾 Sensor Lab 就自動進卡，
  摘要列標「共用元件，自動附上」、README 標 `shared, included for ...`。Sensor Lab 被停用時 QS-Share 照樣執行(沒有用戶端時不改任何東西)。
- Sensor Lab ⟂ RES-Custom(`excl`,同一組 SL_EXCL 掛點):後勾的那個裝成停用(LOADER.BIN 停用清單)。
- `note`:圖磚提示與卡片 README 的「BEFORE YOU COPY」—— 舊的 `SensorLab-IMX410_v0.7.*.BIN` 版本號較大會蓋過 0.0.1test、
  `QSContainer_v*.BIN` 與 QS-Share 同 sup_id,都要先刪。`guide_page`:Sensor Lab 的說明連到 `sensor_lab_imx410/index.html`。
- 測試:`test_merge_v4.js` §8、`test_ui_v4.js` 末段(QS-Share 自動附上且不可選、兩向互斥);「全部可同時執行」那組改用 `plan(...).on`。

驗證範圍(2026-10-24;**`b` 快照的 LOADER、SUPMGR、RESCUS、GYR2、LOSS 已改過，下面「與上機卡相同」只對第一份快照成立**):
- 全選 zip 的每個 sup、RCD、UI 檔與當天上機那張卡逐位元組相同(`fpSup/loader-v4/README.md`「已上線 sup 的 v4 第一次上機」),
  只有開機檔依勾選不同(上機卡多了開機計時標記)。例外:`SHELL.BIN` 是帶 burst15 的移植版，上機時用的是卡上原本那份。
- 未上機：錄影(ULWR、Gyro2 每幀、Lossless 壓縮)、快速啟動組合、Jose 兩個功能本身、ScreenFlip 實際翻轉。
- 本機頁面，未 commit、未發布；網站入口仍指向 merge-v3。
