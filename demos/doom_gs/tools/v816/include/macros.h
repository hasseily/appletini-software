;;; Stand-in for the header "macros.h" of the Calypsi installation
;;; (src/lib/lowlevel), which one upstream source includes and which
;;; this port does not have. Written for the port from public facts;
;;; it is not a copy of the vendor's file, which may hold more.
;;;
;;; It covers the large code model only (upstream's --code-model=large),
;;; and only the three names that the including source uses:
;;;
;;;   libcode   the section of library code. Upstream's linker script
;;;             places no section "libcode", and the library code is in
;;;             the release image among the "farcode" sections.
;;;   return    the manual's list file example (section 22.3.2) shows it
;;;             as a macro that expands to "rtl".
;;;   call      the counterpart of return. The release image has the
;;;             opcode $22 (jsl) at such a call.

#define libcode farcode

return        .macro
              rtl
              .endm

call          .macro  target
              jsl     long:\target
              .endm
