# Lossless 0.3.2test × SensorLab 0.0.5test：14-bit 上機（2026-11-10 18:20–18:30）

## 卡
- 部署：`Lossless_v0.3.2test.BIN`（a174779d…）與正式版 `SensorLab-IMX410_v0.0.5test.BIN`
  （`--settings-from` 卡上 BIN 重建，sha 5064522b…，`out-product/`）。舊 Lossless_v0.3.1 仍在卡上，LOAD.LOG 記 07（被新版取代）。
- LOADER.BIN 沒動：停用清單 RCUS/GYR2/TAPZ/FLIP/RAWV。卡上原檔備份在 `card-before/`，開機後 LOG 在 `LOAD-after.LOG`。
- 換配方用 `setrecipe.py`，讀目前配方用 `payload.py`（sq_test 41/43/19）。第一次推送回 -8，因為相機在 MOV；`menu SetMovRecFormat 0` 後成功。
- 錄影用 `fpSup/lossless/rec_until.py`，狀態用 `card_status.py --layout ../build/layout.json`。
- 鏡頭失焦，壓縮比偏樂觀；Bei：「可以壓縮就好」，所以沒有對焦後重錄。

## 結果
| | A001_180：1936×1090 1:1 AD14，23.976，SD，3 s | A001_181：6048×4040 1:1 AD14，VMAX 16384（≈4.8 fps），SD，10 s |
|---|---|---|
| 收到的格式 | 1936×1090 14-bit，raster 3,692,936 | 6048×4040 14-bit，raster 42,759,360 |
| 壓縮 | 63/63，passed 0，faults 0 | 41/41，passed 0，faults 0 |
| 備用緩衝 | — | spare 42,846,720 B，spare_failed 0，lane_b_failed 0 |
| 每幀大小 | 1,828,864 B（約 2.02:1） | 約 18.94 MB（約 2.26:1） |
| 解碼 | rawpy 成功；f1（未壓縮）與 f2/f3 各 CFA 平均差 <0.1，|diff| ≈ 13.6（雜訊） | rawpy 成功；f1 與 f2 列／欄剖面相關 0.999998，沒有斜切或雜訊 |
| 位元 | BitsPerSample 14；LSB mod 4 均勻（是真的 14-bit） | 同左；tile 512×512 |

- 6K 14-bit 最高 19.03 fps（VMAX 4154 × HMAX 911）。最低約 4.8 fps，受 VMAX ≤ 16384 限制，所以 protocol 原本寫的 3 fps 達不到。
- `verify_compressed_dng.py` 這次判不了：卡上只有一個未壓縮幀可當對照，而且是相鄰幀，檔頭的幀號／時間碼本來就不同。正確性改以解碼比對判定。
- 沒測：SSD、6K 最高 fps 的壓縮／未壓縮交錯、1928 寬的列距閘。
- 結束時用 setrecipe 把配方還原成 Bei 原本的選擇（`G9B-QvQfkGVFwG9ZCIhIvAfUGL8XoPyF6D7ze`，OG 6048×4040 → 3024×2020，12b 2×2）。錄影格式改成了 CinemaDNG。
