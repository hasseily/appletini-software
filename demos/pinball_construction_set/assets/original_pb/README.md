# Original Apple II tables

These DOS 3.3 binary `.PB` files are converted into `.PCS` files by
`tools/make_tables.py` during the build. The converted files include the
object database and the saved Apple II Hi-Res picture. The names here are
at most 11 characters so the `.PCS` files fit ProDOS's 15-character limit.

| This file | Name on source disk | Source image |
| --- | --- | --- |
| `DEMO1.PB`–`DEMO5.PB` | `DEMO1.PB`–`DEMO5.PB` | [San Inc. Apple II disk](https://mirrors.apple2.org.za/ftp.apple.asimov.net/images/games/action/pinball%20construction%20set%20%28san%20inc%20crack%29.dsk) |
| `BCDEMO1.PB` | `DEMO 1.PB` | [Pinball disk 2](https://mirrors.apple2.org.za/ftp.apple.asimov.net/images/games/action/pinball2.dsk) |
| `MINUTEMAGIC.PB` | `MINUTE MAGIC.PB` | same disk |
| `MASTERBLAST.PB` | `MASTER BLASTER.PB` | same disk |
| `FIREBALL.PB` | `FIREBALL.PB` | same disk |
| `THESAW.PB` | `THE SAW.PB` | same disk |
| `METAPIN.PB` | `META PIN.PB` | same disk |

The BudgeCo `DEMO1.PB`–`DEMO3.PB` files on [another archived disk](https://mirrors.apple2.org.za/ftp.apple.asimov.net/images/games/action/pinball_construction_set.dsk) convert
byte-for-byte to the later `DEMO1.PCS`–`DEMO3.PCS`; `MINUTE MAGIC` and
`META PIN` also convert to `DEMO3` and `DEMO2`. `MASTER BLASTER` is the
earlier variant of `DEMO4` and `DEMO 1` differs from the later `DEMO1`.
The empty directory entries named `DEMO8.PB`, `DD.PB`, `AAA.PB`, and
`TEST.PB` on the San Inc. disk are not table files. Its `NEW.PB` is an
unfinished two-object blank without a ball or launcher, so it is not a
playable sample table.

The `pinball2.dsk` data sectors are arranged in reverse sector order
within each track; the extracted files here have their DOS binary headers
and advertised lengths restored. The source disk images themselves are
not needed to rebuild the port.
