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

## 舊的 tag 怎麼辦 —— 2026-09-19 刪掉了

這一節本來寫著「**留著,不改名**。它們已經推上 GitHub,改名會讓任何引用過的
連結失效」。**那個前提是錯的:它們從來沒在 GitHub 上。** 2026-09-19 推四個
新釋出時用了 `git push origin main --follow-tags`,這 16 個才第一次公開,
十分鐘後就刪回來了。沒有連結可以失效,所以留著的理由不存在。

現在本機與 GitHub 都只有符合規則的 tag:**tag 存在 ⟺ `releases/` 有同名的
資料夾**,兩邊逐一相同。

刪掉的 16 個與它們指的 commit —— 全部都是 `main` 的祖先,所以刪的只有標籤,
沒有任何 commit 因此構不到:

```
    fp-gyro-sup-v1.1           933e320d1eb1
    fp-gyro-sup-v1.10a         e5a88b03deb3
    fp-gyro-sup-v1.11a         b1132b12197c
    fp-gyro-sup-v1.11b         05c6e7949d4a
    fp-usb-shell-v2.0.0        3d28e89cebcd
    fp-usb-shell-v3.0.0        24d88016f7b4
    fpGyroSup-v1               707fc33bc70a
    gcsv-edition-six-minutes   ff2af036939a
    gcsv-json-distortion       4c3da72d3405
    gcsv-json-edition          f3fac6697177
    gyr7-11-minutes            b94c34eab7a6
    gyr7-header-complete       cd26eb7f6676
    gyr7-per-take-verified     b94c34eab7a6
    gyro-stream-lossless       afe6d9dbc774
    gyro-stream-stage5-green   89c9681121dc
    gyro-sup-base-v1           4e327b86c0ae
```

要找回某一個:`git tag <名字> <雜湊>`。但先想清楚為什麼 ——
里程碑要記的是「某件事第一次成功」,那是 commit 訊息的工作。

**推釋出時不要用 `--follow-tags`。** 它推的是「從這些 commit 構得到的所有
annotated tag」,不是「這次要發的 tag」。指名要推的那幾個:

```sh
git push origin main
git push origin fpsup-og3k-v0.2.4a fpsup-gyro-v1.12.0
```
