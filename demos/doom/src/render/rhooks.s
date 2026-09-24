; Doom for the Appletini -- the renderer's hooks for the masked phase
; (docs/DESIGN.md section 7).
;
; The masked phase (sprites, two-sided middles, the weapon: tools/
; refrender.py project_sprite, draw_masked, draw_psprite) is the next part
; of the renderer. It plugs in here:
;
;   r_add_sprites   called by the BSP walk (rmain.s subsector) at the first
;                   visit of a sector in the frame, before its segs, with
;                   A/X = the sector: Doom's R_AddSprites (project the
;                   packet's things standing in it). The visit order is
;                   also kept in vs_list_lo/hi (vs_count entries).
;   r_masked        called after the planes: Doom's R_DrawMasked and the
;                   psprites. The drawsegs (ds_n of them) and their
;                   openings are in RENDER_BANK (rsegs.s has the layout);
;                   the packet is in rv_buf.
;
; Until then both do nothing: the view is walls, planes and sky.

.include "kernel.inc"

.segment "RCODE"

r_add_sprites:
        rts

r_masked:
        rts

.export r_add_sprites, r_masked
