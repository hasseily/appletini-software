# game/geom/part.mk: part geom of the game (docs/GAME.md, the parts): the
# side tests, the openings, the point's sector, the block range and the
# block iterators with ITTAB's mechanism; geomt.s is an old driver for
# random checks, assembled empty here (its code needs -D TESTBUILD, which
# no current build defines).
PART := geom
WAVE := 1
geom_SRC := game/geom/geom.s game/geom/giter.s game/geom/geomt.s
geom_ENTRIES := P_PointOnLineSide P_BoxOnLineSide P_LineOpening \
    P_LineOpeningXY pointSector posMul sectorFloor baseFloor baseFloorL \
    baseLite P_BlockLinesIterator P_BlockThingsIterator blockRange
