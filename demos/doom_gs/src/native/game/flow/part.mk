# src/native/game/flow/part.mk: part flow of milestone 10 (docs/GAME.md 2.4,
# wave 1): the game flow game-side (g_game65.s's actions, the load
# protocol's continuations, the demo playback; wi_stuff65.s's ticker and
# counts; ST_Ticker's and HU_Ticker's game effects). Its record:
# docs/game-parts/flow.md.
PART := flow
WAVE := 1
flow_SRC := game/flow/gflow.s game/flow/gwi.s
flow_ENTRIES := loadLevel victory doNewGame doWorldDone doPlayDemo \
    doCompleted doLoadLevel G_ExitLevel G_SecretExitLevel G_WorldDone \
    G_DeferedInitNew G_ReloadDefaults initNew readDemoTiccmd \
    G_DeferedPlayDemo readDemoHeader checkOverrun G_CheckDemoStatus \
    WI_Start WI_End WI_checkForAccelerate WI_Ticker ST_Ticker HU_Ticker \
    signLong div1000 g_resume
