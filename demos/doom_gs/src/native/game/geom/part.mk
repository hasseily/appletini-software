# game/geom/part.mk: part geom of milestone 10 (docs/GAME.md 2.4 row geom,
# 3.3): the side tests, the openings, the point's sector, the block range
# and the block iterators with ITTAB's mechanism; geomt.s is its test
# driver for the random checks (test builds only: TESTBUILD).
PART := geom
WAVE := 1
geom_SRC := game/geom/geom.s game/geom/giter.s game/geom/geomt.s
geom_ENTRIES := P_PointOnLineSide P_BoxOnLineSide P_LineOpening \
    P_LineOpeningXY pointSector posMul sectorFloor baseFloor baseFloorL \
    baseLite P_BlockLinesIterator P_BlockThingsIterator blockRange
