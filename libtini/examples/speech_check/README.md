# Speech check

A text-mode board check for SSI-263 speech on the slot-4 Mockingboard or
Phasor. Boot `build/speech_check.po`. It runs for up to about 25 seconds,
prints one line per test and waits for a key.

```powershell
python tools/build.py --cc65-home D:/Repos/cc65 --game speech_check
```

| Line | Meaning |
| --- | --- |
| `VIA-B T2` | Whether the $C480 VIA's timer 2 counts. The joystick reader uses it when it does |
| `RAW START` | With the driver's speech code off, the SSI is started directly: which VIA set the finished-phoneme CA1 flag, and how soon. `NONE` after 1.00 s means no flag arrived |
| `RAW PHONEMES` | The four phonemes of READY, one at a time: how many finished, how many flags each VIA showed, and the total time |
| `MOCKINGBOARD`, `PHASOR` | The libtini driver says READY and EXCELLENT. `OK` and the time taken, or the first error and when it came. `SEEN` counts finished-phoneme signals sampled before the driver took them; in Phasor mode the interrupt handler takes them first, so it stays 0 |
| `MB+JOYSTICK`, `PH+JOYSTICK` | The same with a joystick read every 30 ms. `J` gives reads and failed reads |

In standalone ONE//e mode on Appletini F1.3.1, every line fails: RAW START
reports `NONE`, RAW PHONEMES `0/4`, and each driver line `TIMING AT 2.00S`.
The card's SSI is clocked only by the Apple's Q3 pin, which no motherboard
drives in that mode.

`TIMING` is the driver's two-second limit for a phoneme that never reports
finishing; after it, further speech is refused until the driver is started
again. In the emulator every line reports success and `VIA-B T2 DOES NOT
COUNT`. Only a board run shows real behaviour.
