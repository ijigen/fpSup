# fpSup agent 入口 / agent entry

製作或修改會隨卡片載入的 sup、AutoRun、loader、stage2、Fast start 或合併建置時，
先完整閱讀 [SUP_BUILD_RULES.md](SUP_BUILD_RULES.md)，再核對實際使用的來源與測試。
此入口只指向同一份規範，不另維護副本；不涉及載入鏈的任務不必擴大成載入鏈重構。
離線建置不代表獲准操作相機、寫卡、commit／push 或發布。
給人看的完整流程說明在 [BUILDING.zh.md](BUILDING.zh.md)。

Before making or changing a sup, AutoRun, loader, stage2, Fast start or a merged
build, read [SUP_BUILD_RULES.en.md](SUP_BUILD_RULES.en.md) in full, then check the
sources and tests actually in use. This entry only points at that contract and
keeps no copy of it; a task that does not touch the load chain should not grow
into a load-chain refactor. An offline build is not permission to operate the
camera, write a card, commit, push or publish. The walkthrough for people is
[BUILDING.md](BUILDING.md).
