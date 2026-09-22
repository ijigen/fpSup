# 三語系頁面產生器

`fpSup/explainers/imx410-binning.html` 與 `rwzm-resampler.html` 是這三個檔產生的,
**不要直接改 HTML**,改 `p1.py` / `p2.py` 再重跑。

```
cd <這個目錄>
python3 p1.py    # → imx410-binning.html
python3 p2.py    # → rwzm-resampler.html
```

- `build.py` —— 樣板(head / 語言列 / footer / 切換 script)與 `build()`。
  輸出路徑寫死在 `OUT`,指向 `fpSup/explainers/`。
- `style3.css` —— 從 `reduction-kernels.html` 抽出來的樣式,已改成三語系:
  `[data-lang=en|cn|zh]` 各自隱藏另外兩個 class。
- `p1.py` 另外提供 `t() / p() / h2() / h3() / table()` 給 `p2.py` 匯入。
  `t(en, cn, zh)` 的三個參數順序固定:**英文、簡體、繁體**。

**檢查方式:** 三種語言的 span 數必須相等(目前 81 / 81 / 81 與 116 / 116 / 116),
而且切換語言後只有該語言的 span 可見。
