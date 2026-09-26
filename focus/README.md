# focus

Code and method for [focus sup](../projects/focus-sup.md).

對焦相關的程式與方法,說明見 [focus sup](../projects/focus-sup.md)。

| | |
|---|---|
| [**dfd/**](dfd/) | Depth from defocus using the camera's own AF statistics — no frame extraction. Method, addresses, and the code that streams the green AF band<br>用相機自己的 AF 統計做 depth-from-defocus,不必抽幀。方法、位址,以及串出綠 AF band 的程式 |
| [**lens/**](lens/) | Reading lens data through the firmware's own API — focal length, minimum focus distance, calibration blocks<br>透過韌體自己的 API 讀鏡頭資料:焦距、最近對焦距離、校準區塊 |

Both target the old USB endpoint and need the two-constant change described in
[dfd/README](dfd/README.md).

兩者都指向舊的 USB 端點,需要 [dfd/README](dfd/README.md) 裡說的那兩個常數修改。
