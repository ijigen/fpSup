# tag 規則

**一條規則:tag 存在 ⟺ `releases/` 底下有同名的資料夾。**

```
releases/fpsup-gyro-v1.11b/   <->   tag fpsup-gyro-v1.11b
```

名字**逐字相同**,不加前綴、不加日期。查「v1.11b 到底是哪個 commit」跟查
「v1.11b 的卡片長什麼樣」是同一個字串。

## 為什麼要有這條

之前 16 個 tag 是三種慣例混在一起:

```
釋出        fp-gyro-sup-v1.11b   fp-usb-shell-v3.0.0   fpGyroSup-v1   gyro-sup-base-v1
里程碑      gyr7-11-minutes   gcsv-json-distortion   gyro-stream-stage5-green   …
```

八個里程碑 tag 標的是「某件事第一次成功」,那是 commit 訊息的工作 ——
而這個 repo 的 commit 訊息本來就寫得夠清楚。混在 `git tag` 的輸出裡,
真正的釋出就被埋掉了。

**更糟的是它害我看漏。** 2026-09-14 我要給 USB shell 訂第一個版本號,
翻了筆記和原始碼,找到作廢的 v27 內部編號,就從 v1.0.0 開始 ——
而 `fp-usb-shell-v3.0.0` 這個 tag 一直在 repo 裡。**釋出紀錄在 tag 裡,
不在筆記裡。** 訂版本前先 `git tag`。

## 舊的 tag 怎麼辦

**留著,不改名。** 它們已經推上 GitHub,改名會讓任何引用過的連結失效,
而它們記錄的東西是真的。新規則從現在開始套用。
