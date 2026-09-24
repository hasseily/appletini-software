/* A blank mobjinfo for unit tests that need only a few of its fields
 * (the test writes them): info.c would pull in every action. */
#include "p_local.h"

const mobjinfo_t mobjinfo[NUMMOBJTYPES];
