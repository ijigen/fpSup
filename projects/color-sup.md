# color sup

色彩科學與 DaVinci 工作流。

**狀態:已有可用成品**

---

## 目標

在後製軟體裡重現 fp 機內的色彩表現,讓 CinemaDNG 素材能對得上機內 JPEG 的觀感。

## 已確認

- **fp 的色彩科學已完整反編譯** —— 從感光元件輸出到最終色彩的整條管線
- **可用的 DCTL** —— 在使用者的 DWG／sRGB 調色流程中,以 in-pipeline 的方式重現
  fp 的 Standard 色彩模式
- 關鍵參數:錨點 `k = 2.124`
- **解碼色彩空間不影響結果** —— 這點反直覺但實測如此,省掉一整類的嘗試

## 未做

- Standard 以外的色彩模式(Vivid、Neutral、Portrait、Monochrome…)
- Teal & Orange 等機內效果
- 色彩模式與 ISO／增益的交互作用

## 相關筆記

`COLOR_SCIENCE`、`ISO_DR_UNDERSTANDING`
