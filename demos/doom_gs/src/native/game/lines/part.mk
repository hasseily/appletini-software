# src/native/game/lines/part.mk: part lines of the game (docs/GAME.md,
# the parts; wave 2): the special lines a thing uses or crosses, the LSTAB
# dispatch of their handlers and the exits, the switch textures and the
# buttons (upstream's p_switch65.s).
PART := lines
WAVE := 2
lines_SRC := game/lines/lines.s
lines_ENTRIES := P_UseSpecialLine P_CrossSpecialLine findSpecial \
    P_ChangeSwitchTexture lnExit
