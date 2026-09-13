# releases —— 每個產品一個資料夾,合併器從這裡自動找最新版

## 命名規則

```
fpsup-<product>-v<major>.<minor>.<patch>[<qualifier>]
```

```
fpsup-gyro-v1.11b          機身端陀螺儀記錄器
fpsup-og3k-v0.1.1test      3:2 全片幅錄影(全 ISO)
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
README.txt    給使用者
MANIFEST.txt  可選,雜湊與建置紀錄
```

`AutoRun.txt` 與 `VSHL.BIN` 就是卡片的全部 —— 放進 SD 卡根目錄即可。

## 版本從哪裡接下去

**接 `git tag`,不要接筆記。** USB shell 的上一個釋出是 tag `fp-usb-shell-v3.0.0`,
所以這次是 **v3.1.0** —— 自那之後 `fp_usb_shell/` 有 16 個 commit(echo 啟動、
熱抽換、載入器改從指令啟動),但 `shl` 的介面沒變,舊卡照樣能用,所以是 minor。

(筆記裡看得到 v27 那種編號,那是**已作廢的內部迭代** —— 走 EP 0x05 / EP 0x84,
而 EP 0x84 在現行描述元下不存在。別拿它接。)

## 加一個新版本

建好卡片,放進 `fpsup-<product>-v<版本>/`,跑一次
`tools/card-composer/build_catalogue.py`。合併器會自己挑到新的那個 ——
不需要改程式。

---

**fpSup** · [Ko-fi](https://ko-fi.com/fpsup) · [Discord](https://discord.gg/XeFK5zNZpT)
